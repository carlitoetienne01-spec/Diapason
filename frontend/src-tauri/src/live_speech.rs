//! Live dictation on Apple's on-device speech recogniser.
//!
//! Why this lives in the Tauri process rather than the Python backend: speech
//! recognition is a TCC-protected resource, and macOS does not merely refuse it
//! when the requesting binary has no usage description — it aborts the process
//! outright (SIGABRT) the instant `requestAuthorization:` is called. Only a
//! bundled, signed app carrying `NSSpeechRecognitionUsageDescription` in its
//! Info.plist may ask. That is this crate, not `python -m diapason`.
//!
//! The pipeline is: AVAudioEngine taps the microphone, every captured buffer is
//! appended to an `SFSpeechAudioBufferRecognitionRequest`, and the recogniser
//! calls back with a steadily-refined transcript. Partial results arrive every
//! few hundred milliseconds and *replace* the previous partial rather than
//! extending it — the recogniser revises its own guesses as more audio arrives
//! ("recognise" may become "recognised" a word later). Callers must therefore
//! treat a non-final payload as the whole of the current segment.

#[cfg(target_os = "macos")]
mod imp {
    use std::ptr::NonNull;
    use std::sync::atomic::{AtomicBool, Ordering};
    use std::sync::mpsc;
    use std::sync::Mutex;
    use std::time::Duration;

    use block2::RcBlock;
    use objc2::rc::Retained;
    use objc2::AllocAnyThread;
    use objc2_avf_audio::{AVAudioEngine, AVAudioPCMBuffer, AVAudioTime};
    use objc2_foundation::{NSError, NSLocale, NSString};
    use objc2_speech::{
        SFSpeechAudioBufferRecognitionRequest, SFSpeechRecognitionResult, SFSpeechRecognitionTask,
        SFSpeechRecognizer, SFSpeechRecognizerAuthorizationStatus,
    };
    use serde::Serialize;
    use tauri::{AppHandle, Emitter};

    /// Emitted for every revision of the transcript.
    ///
    /// `text` is the entire current segment, not a delta. `is_final` marks the
    /// point where the recogniser stops revising and the words are settled.
    #[derive(Clone, Serialize)]
    pub struct LiveTranscript {
        pub text: String,
        #[serde(rename = "isFinal")]
        pub is_final: bool,
    }

    #[derive(Clone, Serialize)]
    pub struct LiveError {
        pub message: String,
    }

    pub const EVENT_TRANSCRIPT: &str = "live-dictation";
    pub const EVENT_ERROR: &str = "live-dictation-error";

    /// Live objects for one dictation run. None of these are `Send`, but every
    /// touch of them happens on the main thread (see `on_main`), so the manual
    /// assertion below is sound.
    struct Session {
        engine: Retained<AVAudioEngine>,
        recognizer: Retained<SFSpeechRecognizer>,
        task: Retained<SFSpeechRecognitionTask>,
        /// The tap block must outlive the tap that AVFoundation installed.
        _tap: RcBlock<dyn Fn(NonNull<AVAudioPCMBuffer>, NonNull<AVAudioTime>)>,
        locale: Option<String>,
    }
    unsafe impl Send for Session {}

    /// The request the audio tap currently feeds. Held apart from `Session`
    /// because a recognition task is replaced mid-run (see `restart`) while the
    /// audio tap keeps running untouched: swapping this slot re-points the
    /// microphone at the new request without an audible gap.
    struct RequestSlot(Option<Retained<SFSpeechAudioBufferRecognitionRequest>>);
    unsafe impl Send for RequestSlot {}

    static SESSION: Mutex<Option<Session>> = Mutex::new(None);
    static REQUEST: Mutex<RequestSlot> = Mutex::new(RequestSlot(None));
    static ACTIVE: AtomicBool = AtomicBool::new(false);

    /// Runs `f` on the main thread and waits for its result.
    ///
    /// Callers must be async Tauri commands: those are dispatched onto the
    /// async runtime, so blocking here cannot deadlock the main thread. A
    /// synchronous command would run *on* the main thread and wait forever.
    fn on_main<F, T>(app: &AppHandle, f: F) -> Result<T, String>
    where
        F: FnOnce() -> Result<T, String> + Send + 'static,
        T: Send + 'static,
    {
        let (tx, rx) = mpsc::channel();
        app.run_on_main_thread(move || {
            let _ = tx.send(f());
        })
        .map_err(|e| format!("main thread unavailable: {e}"))?;
        rx.recv_timeout(Duration::from_secs(15))
            .map_err(|_| "speech setup timed out".to_string())?
    }

    fn make_recognizer(locale: Option<&str>) -> Result<Retained<SFSpeechRecognizer>, String> {
        let recognizer = unsafe {
            match locale {
                Some(id) if !id.is_empty() => {
                    let ns = NSLocale::localeWithLocaleIdentifier(&NSString::from_str(id));
                    SFSpeechRecognizer::initWithLocale(SFSpeechRecognizer::alloc(), &ns)
                }
                _ => SFSpeechRecognizer::init(SFSpeechRecognizer::alloc()),
            }
        };
        let recognizer = recognizer.ok_or_else(|| {
            "speech recognition is not available for this language".to_string()
        })?;
        if !unsafe { recognizer.isAvailable() } {
            return Err("the speech recogniser is temporarily unavailable".to_string());
        }
        Ok(recognizer)
    }

    /// Builds a request configured for streaming, preferring on-device
    /// recognition so audio never leaves the Mac. Server-based recognition is
    /// also rate-limited and capped at about a minute per task, which would
    /// make continuous dictation unreliable even setting privacy aside.
    fn make_request(
        recognizer: &SFSpeechRecognizer,
    ) -> Retained<SFSpeechAudioBufferRecognitionRequest> {
        let request = unsafe {
            SFSpeechAudioBufferRecognitionRequest::init(
                SFSpeechAudioBufferRecognitionRequest::alloc(),
            )
        };
        unsafe {
            request.setShouldReportPartialResults(true);
            if recognizer.supportsOnDeviceRecognition() {
                request.setRequiresOnDeviceRecognition(true);
            }
        }
        request
    }

    /// Installs the result callback and returns the running task.
    fn spawn_task(
        app: &AppHandle,
        recognizer: &SFSpeechRecognizer,
        request: &SFSpeechAudioBufferRecognitionRequest,
    ) -> Retained<SFSpeechRecognitionTask> {
        let app_for_handler = app.clone();
        let handler = RcBlock::new(
            move |result: *mut SFSpeechRecognitionResult, error: *mut NSError| {
                let mut settled = false;

                if let Some(result) = unsafe { result.as_ref() } {
                    let is_final = unsafe { result.isFinal() };
                    let text =
                        unsafe { result.bestTranscription().formattedString() }.to_string();
                    settled |= is_final;
                    if !text.is_empty() {
                        let _ = app_for_handler.emit(
                            EVENT_TRANSCRIPT,
                            LiveTranscript { text, is_final },
                        );
                    }
                }

                if let Some(error) = unsafe { error.as_ref() } {
                    settled = true;
                    // Code 301 ("recognition request was canceled") is the
                    // ordinary consequence of stopping, not a fault worth
                    // showing anyone.
                    let code = error.code();
                    if ACTIVE.load(Ordering::SeqCst) && code != 301 && code != 216 {
                        let message = error.localizedDescription().to_string();
                        let _ = app_for_handler.emit(EVENT_ERROR, LiveError { message });
                    }
                }

                // A task ends on its own after a stretch of speech; keep the
                // microphone alive by starting a fresh one so dictation can run
                // as long as the user keeps talking.
                if settled && ACTIVE.load(Ordering::SeqCst) {
                    let app_for_restart = app_for_handler.clone();
                    let _ = app_for_handler.run_on_main_thread(move || {
                        restart(&app_for_restart);
                    });
                }
            },
        );

        unsafe { recognizer.recognitionTaskWithRequest_resultHandler(request, &handler) }
    }

    /// Swaps in a new request and task without disturbing the audio tap.
    fn restart(app: &AppHandle) {
        if !ACTIVE.load(Ordering::SeqCst) {
            return;
        }
        let mut guard = match SESSION.lock() {
            Ok(guard) => guard,
            Err(_) => return,
        };
        let Some(session) = guard.as_mut() else {
            return;
        };

        // A recogniser that has gone unavailable (device asleep, language pack
        // evicted) yields nil tasks forever; rebuild it rather than spin.
        let recognizer = match make_recognizer(session.locale.as_deref()) {
            Ok(recognizer) => recognizer,
            Err(_) => return,
        };
        let request = make_request(&recognizer);
        let task = spawn_task(app, &recognizer, &request);

        if let Ok(mut slot) = REQUEST.lock() {
            slot.0 = Some(request);
        }
        session.recognizer = recognizer;
        session.task = task;
    }

    /// Asks the user for permission, once, and reports the settled status.
    fn authorize() -> Result<(), String> {
        let (tx, rx) = mpsc::channel();
        let block = RcBlock::new(move |status: SFSpeechRecognizerAuthorizationStatus| {
            let _ = tx.send(status.0);
        });
        unsafe { SFSpeechRecognizer::requestAuthorization(&block) };

        // The prompt is modal for the user, not for us, so allow real time to
        // read it.
        let status = rx
            .recv_timeout(Duration::from_secs(120))
            .map_err(|_| "no answer to the speech recognition prompt".to_string())?;

        match status {
            3 => Ok(()),
            1 => Err(
                "speech recognition was denied — enable Diapason in System Settings › Privacy & Security › Speech Recognition"
                    .to_string(),
            ),
            2 => Err("speech recognition is restricted on this Mac".to_string()),
            _ => Err("speech recognition permission was not granted".to_string()),
        }
    }

    pub fn available() -> bool {
        // Constructing a recogniser touches no protected resource, so this is
        // safe to call before any authorisation prompt.
        make_recognizer(None).is_ok()
    }

    pub fn start(app: &AppHandle, locale: Option<String>) -> Result<(), String> {
        if ACTIVE.load(Ordering::SeqCst) {
            return Ok(());
        }
        authorize()?;

        let app_for_setup = app.clone();
        let locale_for_setup = locale.clone();
        on_main(app, move || {
            let recognizer = make_recognizer(locale_for_setup.as_deref())?;
            let request = make_request(&recognizer);

            let engine = unsafe { AVAudioEngine::init(AVAudioEngine::alloc()) };
            let input = unsafe { engine.inputNode() };
            let format = unsafe { input.outputFormatForBus(0) };

            // A zero sample rate means no usable input device; installing a tap
            // with that format throws an Objective-C exception, which would
            // abort the process rather than surface an error.
            if unsafe { format.sampleRate() } <= 0.0 {
                return Err("no microphone is available".to_string());
            }

            let tap = RcBlock::new(
                move |buffer: NonNull<AVAudioPCMBuffer>, _when: NonNull<AVAudioTime>| {
                    // Runs on the audio thread. `try_lock` keeps it from ever
                    // blocking there: the only contender is a task swap, and
                    // losing one buffer to it is inaudible.
                    if let Ok(slot) = REQUEST.try_lock() {
                        if let Some(request) = slot.0.as_ref() {
                            unsafe { request.appendAudioPCMBuffer(buffer.as_ref()) };
                        }
                    }
                },
            );

            if let Ok(mut slot) = REQUEST.lock() {
                slot.0 = Some(request.clone());
            }

            unsafe {
                input.installTapOnBus_bufferSize_format_block(
                    0,
                    2048,
                    Some(&format),
                    // AVFoundation copies the block, but the copy borrows our
                    // captured state, so `tap` is parked in the session below.
                    &*tap as *const _ as *mut _,
                );
                engine.prepare();
            }

            if let Err(error) = unsafe { engine.startAndReturnError() } {
                unsafe { input.removeTapOnBus(0) };
                if let Ok(mut slot) = REQUEST.lock() {
                    slot.0 = None;
                }
                return Err(format!(
                    "could not start the microphone: {}",
                    error.localizedDescription()
                ));
            }

            ACTIVE.store(true, Ordering::SeqCst);
            let task = spawn_task(&app_for_setup, &recognizer, &request);

            if let Ok(mut guard) = SESSION.lock() {
                *guard = Some(Session {
                    engine,
                    recognizer,
                    task,
                    _tap: tap,
                    locale: locale_for_setup,
                });
            }
            Ok(())
        })
    }

    pub fn stop(app: &AppHandle) -> Result<(), String> {
        // Cleared first so the result handler treats the imminent cancellation
        // as expected and does not immediately restart the task.
        ACTIVE.store(false, Ordering::SeqCst);

        on_main(app, move || {
            if let Ok(mut slot) = REQUEST.lock() {
                if let Some(request) = slot.0.take() {
                    unsafe { request.endAudio() };
                }
            }
            if let Ok(mut guard) = SESSION.lock() {
                if let Some(session) = guard.take() {
                    unsafe {
                        session.engine.inputNode().removeTapOnBus(0);
                        session.engine.stop();
                        // `finish` lets the tail of the audio be transcribed;
                        // `cancel` would discard the last words spoken.
                        session.task.finish();
                    }
                }
            }
            Ok(())
        })
    }
}

#[tauri::command]
pub async fn live_dictation_available() -> bool {
    #[cfg(target_os = "macos")]
    {
        imp::available()
    }
    #[cfg(not(target_os = "macos"))]
    {
        false
    }
}

#[tauri::command]
pub async fn start_live_dictation(
    #[allow(unused_variables)] app: tauri::AppHandle,
    #[allow(unused_variables)] locale: Option<String>,
) -> Result<(), String> {
    #[cfg(target_os = "macos")]
    {
        imp::start(&app, locale)
    }
    #[cfg(not(target_os = "macos"))]
    {
        Err("live dictation requires macOS".to_string())
    }
}

#[tauri::command]
pub async fn stop_live_dictation(
    #[allow(unused_variables)] app: tauri::AppHandle,
) -> Result<(), String> {
    #[cfg(target_os = "macos")]
    {
        imp::stop(&app)
    }
    #[cfg(not(target_os = "macos"))]
    {
        Ok(())
    }
}
