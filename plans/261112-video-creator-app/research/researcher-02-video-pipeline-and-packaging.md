# Research 02: Video pipeline và đóng gói (2026-11-12)

Ghi chú: đã dùng hết ngân sách tra cứu web. "chưa xác nhận" = kiến thức sẵn có, chưa tra nguồn hiện hành.

## 1. rea-video (JuneYaooo/rea-video)

**Khuyến nghị: CLI chạy standalone được (không cần agent) cho shot detection + OCR + phân tích tất định. Test trên Windows ngày 1; lùi về PySceneDetect + Gemini nếu hỏng.**

- Yêu cầu: Python >= 3.10, ffmpeg. Cài (chưa có PyPI name/version):
  ```bash
  git clone <repo> && cd rea-video
  pip install -e ".[ocr]"
  rea-video --help
  ```
  Lỗi OpenCV: `pip uninstall -y opencv-python && pip install --force-reinstall --no-deps "opencv-python-headless>=4.8,<5"`.
- Lệnh chính:
  ```bash
  rea-video decompose ref.mp4 -o out/ref --no-packaging --max-vlm-shots 60
  rea-video stems ref.mp4 -o out/ref   # original/vocals/music/effects .wav
  ```
  Flag khác: `--vlm`, `--no-ocr`, `--ocr-lang zh|ja`, `--lang zh|en`, `--no-asr`.
- Không cần agent: tất định (không model); `--vlm` (model multimodal OpenAI-compatible); agent điền `review_answers.json` (`review`/`apply-review`). Trang khuyến nghị skill-agent, nhưng không bắt buộc.
- Output: `breakdown.json`, `report.html/.md`, `VIDEO.md` + `video/`, `storyboard.jpg`, frame đầu/cuối shot, `packaging/` (SRT, ASS), `sfx/`. Schema đầy đủ `VIDEO.md`: chưa xác nhận.
- Cấu hình VLM (không có mục Gemini riêng):
  ```
  REA_VLM_BASE_URL=https://.../v1   # endpoint Gemini OpenAI-compat: chưa xác nhận
  REA_VLM_API_KEY=...
  REA_VLM_MODEL=gemini-2.5-pro,gpt-4o
  ```
  Nạp bằng `rea-video --env-file <path>`.
- Model: UVR MDX-Net ~67 MB; BandIt v2 ~149 MB (CC BY-SA 4.0); OCR JP ~10 MB; cache `$REA_VIDEO_MODELS`. Torch: không thấy nhắc.
- CPU: video 30s không VLM ~1 phút; BandIt ~1.5x độ dài audio; packaging thêm 30–50 s/phút.
- Windows: **không đề cập**; hướng dẫn chỉ macOS/Ubuntu, script cài bằng bash. Nguồn: https://raw.githubusercontent.com/JuneYaooo/rea-video/main/docs/cli.md

## 2. Gemini video understanding (google-genai)

**Khuyến nghị: `google-genai` SDK + Files API; ghim model ID sau khi `client.models.list()`.**

- Cài: `uv add google-genai`
  ```python
  from google import genai
  client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
  f = client.files.upload(file="shot_01.mp4")
  while f.state.name == "PROCESSING":
      time.sleep(5)
      f = client.files.get(name=f.name)
  resp = client.models.generate_content(model="<MODEL_ID>", contents=[f, "Mô tả cảnh..."])
  ```
- Model: trang dùng ví dụ `gemini-3.8-flash`; agentic trên Gemini 4 Carbon/Argon, 3.8 Flash, 3.6 Flash, 3.5 Flash Lite. Model cuối: chưa xác nhận.
- Token: ~100 token/s (độ phân giải thấp, mặc định), ~300 token/s (cao); frame 66/258 token; audio 32 token/s. Ước 1 phút thấp ≈ 8k token.
- Giới hạn: inline < 100 MB (trang cũng ghi "dưới 20 MB" cho khuyến nghị); Files API 20 GB trả phí / 2 GB miễn phí; context 1M ≈ 3 giờ (độ phân giải thấp). Định dạng: mp4, mov, webm, mpeg, avi, flv, wmv, 3gpp. YouTube URL: preview, chỉ video public.
- Structured output (`response_mime_type` + `response_schema`) và retention 48 giờ: chưa xác nhận trên trang đã đọc. Vẫn validate bằng Pydantic.
- Giá/phút video: **chưa xác nhận**; lấy từ https://ai.google.dev/gemini-api/docs/pricing.
- Nguồn: https://aistudio.google.com/docs/video-understanding (redirect từ ai.google.dev)

## 3. TTS tiếng Việt + Anh

**Khuyến nghị: Gemini TTS mặc định (cùng API key, đã có trong stack); OpenAI `gpt-4o-mini-tts` dự phòng. Không dùng edge-tts cho sản phẩm thương mại. Bắt buộc nghe thử tiếng Việt trước khi chốt.**

| Tiêu chí | Gemini TTS | OpenAI gpt-4o-mini-tts | ElevenLabs | edge-tts |
|---|---|---|---|---|
| Giá (nguồn thứ cấp) | ~$0.50/1M text in, ~$9/1M audio out (đến 31/12/2026) | ~$0.015/phút audio | $50–100/1M ký tự | miễn phí |
| Tiếng Việt | Có; điểm 8.5/10 (bảng cũ, không benchmark) | 7.5/10 (bảng cũ) | Việt trong 32 ngôn ngữ: chưa xác nhận | Có |
| Thương mại | Free tier dùng dữ liệu cải thiện sản phẩm; trả phí: chưa xác nhận | API trả phí: chưa xác nhận | Chỉ gói trả phí | **Không rõ, rủi ro** |

- Giá thứ cấp, cần đối chiếu trang chính thức. Nguồn: https://tokencost.app/blog/tts-api-pricing-2026 ; https://tech-insider.org/ca/elevenlabs-vs-openai-vs-google-gemini-tts-2026/ ; https://speechify.ai/blog/tts-api-pricing-at-volume-2026
- Thiết kế: `TTSProvider.synthesize(text, lang) -> wav`.

## 4. FFmpeg: shot, phụ đề, mix, beat

**Khuyến nghị: re-encode shot về cùng codec/fps/size rồi concat; phụ đề ASS + filter `subtitles` với file ASCII trong thư mục làm việc; ducking `sidechaincompress`; chuẩn hoá `loudnorm`; beat bằng librosa.**

- Cắt + 9:16 mỗi shot:
  ```bash
  ffmpeg -ss 12.40 -t 3.20 -i in.mp4 -an \
    -vf "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,fps=30" \
    -c:v libx264 -preset veryfast -crf 20 -pix_fmt yuv420p seg_01.mp4
  ffmpeg -f concat -safe 0 -i list.txt -c copy video_cut.mp4
  ```
- Phụ đề (Windows): chạy trong thư mục làm việc, tên ASCII, tránh escape đường dẫn tiếng Việt:
  ```bash
  ffmpeg -i video_cut.mp4 -vf "subtitles=sub.ass:fontsdir=fonts" -c:a copy out.mp4
  ```
  Font `.ttf` (ví dụ Be Vietnam Pro) trong `fonts/`; `Fontname` trong ASS khớp tên family. Kiểm tra build có libass: `ffmpeg -filters | findstr subtitles`.
- Ducking + loudness:
  ```bash
  ffmpeg -i video.mp4 -i music.wav -i vo.wav -filter_complex \
  "[1:a][2:a]sidechaincompress=threshold=0.05:ratio=8:attack=20:release=300[duck];\
   [duck][2:a]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=11[a]" \
  -map 0:v -map "[a]" -c:v copy -c:a aac -b:a 192k out.mp4
  ```
- Beat: **librosa** (`pip install librosa`, wheel Windows Python 3.11 có sẵn; chưa xác nhận bản hiện hành). aubio trên Windows: chưa xác nhận.
  ```python
  y, sr = librosa.load(music, sr=22050, mono=True)
  _, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
  beat_times = librosa.frames_to_time(beat_frames, sr=sr)
  ```
- Nguồn: kiến thức sẵn có, chưa tra tài liệu FFmpeg hiện hành; cần test thực tế.

## 5. Đóng gói Windows

**Khuyến nghị: Inno Setup + venv build sẵn bằng uv + `ffmpeg.exe` bundle + pywebview. Không PyInstaller: rea-video kéo onnxruntime/opencv và gọi CLI thứ hai qua subprocess, dễ lỗi hidden imports.**

- pywebview: backend Windows mặc định là WebView2. Win 10 có thể cần Evergreen Runtime (chưa xác nhận); installer kiểm tra và cài nếu thiếu.
  ```python
  threading.Thread(target=uvicorn.run, args=(app,), kwargs={"host":"127.0.0.1","port":port}, daemon=True).start()
  # chờ /health rồi:
  webview.create_window("Video Creator", f"http://127.0.0.1:{port}")
  webview.start()   # main thread
  ```
- uv: `uv venv`, `uv sync --frozen`. Venv có di dời sau khi cài Inno: chưa xác nhận, kiểm tra trên máy thứ hai.
- FFmpeg: build gyan.dev hoặc BtbN; kiểm tra license (GPL/LGPL) vì ảnh hưởng nghĩa vụ phân phối (chưa xác nhận). Gọi đường dẫn tuyệt đối `{app}\ffmpeg\bin\ffmpeg.exe`.
- Single-instance: named mutex (`ctypes.windll.kernel32.CreateMutexW`); nếu đã chạy thì mở lại URL.
- Data dir: `%APPDATA%\VideoCreator\` qua `platformdirs.user_data_dir("VideoCreator")`: `config.toml`, `app.db`, `secrets`, `media/`. Export/import zip để chuyển máy.
- Nguồn: https://pywebview.flowrl.com/ ; https://docs.astral.sh/uv/ ; https://jrsoftware.org/isinfo.php (kiến thức sẵn có, chưa mở trong lượt này)

## 6. python-telegram-bot trong loop chung FastAPI + APScheduler

**Khuyến nghị: PTB v22 async, khởi tạo trong lifespan FastAPI (`initialize/start/updater.start_polling`); không dùng `run_polling()` vì nó tự tạo loop. Allowlist bằng `filters.Chat` + kiểm tra trong callback. Preview gửi bằng `send_video`.**

- Cài: `uv add "python-telegram-bot==22.*"` (bản vá: chưa xác nhận).
  ```python
  @asynccontextmanager
  async def lifespan(app):
      tg = Application.builder().token(TOKEN).build()
      tg.add_handler(CommandHandler("status", status, filters=ALLOWED))
      tg.add_handler(CallbackQueryHandler(on_decision, pattern=r"^(ok|no):\d+$"))
      await tg.initialize(); await tg.start(); await tg.updater.start_polling()
      scheduler.start()          # AsyncIOScheduler, cùng loop
      yield
      await tg.updater.stop(); await tg.stop(); await tg.shutdown()
  ```
- Allowlist: `ALLOWED = filters.Chat(chat_id=ALLOWED_IDS)`, đọc ID từ config; kiểm tra lại `update.effective_chat.id` trong callback.
- Nút duyệt:
  ```python
  kb = InlineKeyboardMarkup([[InlineKeyboardButton("Duyệt", callback_data=f"ok:{vid}"),
                              InlineKeyboardButton("Loại", callback_data=f"no:{vid}")]])
  await bot.send_video(chat_id, video=open(preview, "rb"), reply_markup=kb, supports_streaming=True)
  ```
  `callback_data` chỉ chứa id, dưới 64 byte (chưa xác nhận lại).
- Giới hạn: Bot API chuẩn upload khoảng 50 MB, getFile khoảng 20 MB (kiến thức sẵn có, trang đọc được không tới phần này). Local Bot API server: upload 2000 MB, download không giới hạn (đã xác nhận, Bot API 10.4 cập nhật 2026-11-09). Preview 720p ~10–20 MB là đủ.
- Nguồn: https://core.telegram.org/bots/api ; https://docs.python-telegram-bot.org/ (chưa mở trong lượt này)

## Chưa xác nhận / câu hỏi mở

- rea-video: PyPI name/version; chạy trên Windows; schema `VIDEO.md`; có cần `[ocr]` cho decompose; `[asr]` size.
- Gemini: giá/phút video; model ID cuối; structured output; retention 48 giờ.
- TTS: điều khoản thương mại của Gemini TTS trả phí; chất lượng tiếng Việt thực tế; giá cần đối chiếu.
- FFmpeg: build Windows có libass; license build; font Việt được bundle.
- librosa/aubio hiện hành trên Windows; venv uv có di dời được không.
- WebView2 trên Win 10 máy đích.
- Telegram: giới hạn chuẩn sendVideo/getFile, callback_data (kiến thức sẵn có).
