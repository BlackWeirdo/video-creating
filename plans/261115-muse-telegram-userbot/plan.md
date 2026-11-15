# Provider `muse_tg`: Muse qua tai khoan Telegram ca nhan (Telethon)

Quyet dinh chu 2026-11-15 (chap nhan rui ro ToS/ban). Thay `muse_fox` (FoxProfile REST) trong FR-AI-10. FoxProfile REST = phuong an sau, YAGNI.
Roles: `vision`, `writer`, `checker`. Route mac dinh KHONG doi (khong co `muse_tg` trong default lists) => tat cho den khi chu tu them vao Settings.

Quyet dinh chu (2026-11-15, da tra loi):
- TK Telegram login = TK ca nhan = admin Muse2Tele (8273197414). Khong Premium => `caption_limit=1024`.
- App dung **TK Muse thu 2** => profile FoxProfile rieng => **topic rieng** (Muse2Tele: 1 profile = 1 topic, khong co cach mo topic thu 2 cho cung profile; 1 TK Muse tren 2 profile = rui ro khoa, loai). Topic `MuseAI` (6) cua chu KHONG dung.
- `max_requests_per_day=60` OK. Login qua CLI terminal OK.
- `api_id`/`api_hash` chu da cap; khi code luu vao SecretsStore, KHONG ghi vao repo/config.toml/log/memory.
- Thu vien: Telethon (PyPI on dinh, `StringSession` gon; repo chuyen sang Codeberg). Kurigram la phuong an du phong neu Telethon loi voi forum topic.

## 1. Muse2Tele protocol (code-verified, C:\MuseAI\Muse2Tele\muse_telebot\muse_telebot.py)

Vao (user -> bot):
- Chi nhan tin tu `admin_id()` (state `admin` = 8273197414) VA chat = `group_id()` (-1004323226935 "Muse AI Bot"); topic -> profile qua `state.teams.default.topics` (hien chi `MuseAI`: topic 6; profile moi cua app se duoc bot tu tao topic khi dang nhap Muse xong, l.2080/2157). Tin tu bot bi bo (`_forward` l.398/5319). Tin bat dau `/` bi bo. Topic la General/khong map -> bot reply "Topic nay khong gan voi profile nao".
- => TK userbot PHAI la chinh TK admin. Gui bang `reply_to=<topic_id>` (bot coi reply vao tin mo topic = khong co reply-context, l.481). KHONG reply tin khac.
- Moi profile = 1 hang doi tuan tu (`profile_queues`), album gom theo `media_group_id` (ALBUM_WAIT 2s). Tin chua co Muse nhan => bot tu retry/stall (MUSE_DOWN_TEXT), bo cuoc sau 30 phut.
- File: bot tai qua Bot API getFile => **toi da 20 MB/file** (`TG_DOWNLOAD_LIMIT`); vuot thi bot KHONG gui gi cho Muse, reply "Bot khong tai duoc file ... CHUA gui gi" + react 👎. => video phai nen <= ~15 MB.
- Text kem file = `caption` => **gioi han caption Telegram 1024 ky tu (4096 neu Premium)**; text thuan 4096.
- Link http(s) trong text: `attach_samples` co the tai video mau (chi khi team bat skill video) => loc URL khoi prompt (thay `[link]`).

Ra (bot -> topic):
- Phan hoi Muse gui ve topic bang bot, chia chunk <=4000 ky tu, HTML (code block -> `<pre>`), co the kem nut (inline keyboard), anh/video. Tin "⚙️ <ten>: <status>" la tin trang thai Muse dang lam, sua tai cho roi xoa => BO QUA khi gom reply.
- Reaction bot dat len TIN CUA MINH (tin userbot gui): 👀 = bot da nhan/enqueue; 👍 = da dua vao Muse; 👎 = that bai; 👌 = Muse **xong luot** (relay idle 3 poll x1.5s sau busy). Day la tin hieu "xong" chinh.
- Thong bao loi dang text tu bot (reply vao tin minh): `⏳ Muse dang gap loi...` (Muse down, bot tu gui lai), `⚠️ Chua gui duoc cho Muse`, `⚠️ Bot khong tai duoc file`, `❌ Muse van dang loi`, `⏳ ... bot ngung cho` (sau toi da 2h), `🔁 Muse chua nhan tin truoc`.
- Muse co the gui tin "meo/quang cao" tu do; co "link rule" (Muse gui link tai sau moi file) => ignore, chi can JSON.
- Khong co marker task-id/score, khong co JSON mode, khong co queue/busy API: busy chi suy ra tu hang doi cua bot (tin cua minh den sau tin cua chu => cho).

=> Giao thuc userbot: (1) gui tin co tag `VC#<id8>`; (2) poll topic `min_id=sent_id` moi 2s; (3) tin hieu: 👀 trong 20s (khong co => bot offline); 👌 = xong; 👎/notice loi = fail; fallback "yen lang" 25s sau tin bot cuoi va khong co tin ⚙️ dang sua; hard timeout theo role. (4) gom text cac tin bot (id > sent_id, bo ⚙️, bo notice) -> trich JSON.
**Phase 0 spike phai xac nhan**: reaction cua bot co doc duoc qua `GetMessagesReactions` khong (Telethon `message.reactions.results`); neu khong thi dung fallback yen lang lam chinh.

## 2. Thiet ke

Thu vien: `telethon` (them vao pyproject, import lazy trong ham de app khoi dong khong phu thuoc). Moi lan goi: `asyncio.run(...)` trong thread worker (JobWorker don luong; nut test dung `asyncio.to_thread`), connect -> lam viec -> disconnect (KISS, khong giu ket noi dai). Session = `StringSession` luu trong `SecretsStore` (DPAPI tren Windows, 0600 tren POSIX) => khong co file .session roi rac, khong tu quyen nguoi dung khac. `register_secret_for_redaction` cho api_hash + session.

Secrets: `MUSE_TG_API_ID`, `MUSE_TG_API_HASH`, `MUSE_TG_SESSION` (chi ghi bang `muse-login`; UI chi hien Da dat/Xoa).
Config (`config_ai.py`, `AIConfig.muse_tg: MuseTgConfig`): `group_id: int = 0`, `topic_id: int = 0`, `vision_mode: "auto"|"video"|"frames" = "auto"`, `max_video_mb: int = 15`, `max_video_s: int = 60`, `caption_limit: int = 1024`, `timeout_vision_s: 360`, `timeout_text_s: 240`, `min_gap_s: 5`, `max_requests_per_day: 60`.
Khong co co `enabled` rieng: bat = them `muse_tg` vao route + da du secrets/config (YAGNI). Thieu cau hinh => `ProviderAuthError` => router bo qua, sang provider ke.

Interface fit router: `name="muse_tg"`, `route_kind="subscription"` (khong tinh tien, `record_usage(route="subscription", units_in/out = so ky tu)`, khong qua `check_budget`; `api_fallback=ask/never` khong chan no, va khi no nghi thi cac nha API ke tiep theo policy nhu cu). `describe_video(video, prompt, schema, thumbnails=)` va `generate_json(prompt, schema)`.
Loi -> ngoai le co san: FloodWaitError -> `ProviderQuotaExhausted(retry_after_s=seconds+30)`; Muse tra loi dang "het han muc/limit" (tai dung `QUOTA_PATTERNS` tu `cli_base`) -> `ProviderQuotaExhausted(3600)`; AuthKeyUnregistered/SessionRevoked/UserDeactivated/chua login -> `ProviderAuthError`; bot offline (khong 👀 sau 20s)/topic missing (`MessageIdInvalid`/`TopicClosed`/bot notice)/timeout/👎 -> `AIError` (router tu thu provider ke, `mark_provider_error`). Nghi that bai 3 lan lien tiep khong lam them (YAGNI).

Tuan tu hoa: lock tien trinh `threading.Lock` quanh toan bo 1 luot gui->xong (1 in-flight). Cho lock toi da `timeout` roi `AIError("muse_tg busy")`. Worker job da don luong nen analyse queue tu tuan tu; lock chi chong nut Test song song. Khoang cach toi thieu giua 2 luot `min_gap_s` (anti-flood). Cap `max_requests_per_day` dem tu `ai_usage` (provider='muse_tg') -> vuot thi `ProviderQuotaExhausted` den het ngay UTC. Topic rieng chi app dung => KHONG can kiem tra "chu dang go tay" (YAGNI). Chi giu: neu tin bot cuoi cung trong topic la ⚙️ dang sua (luot truoc bi timeout chua xong) -> cho yen lang toi da 60s, khong thi `AIError("Muse busy")`.

Prompt: `VC#<id8>` dau dong, tieng Viet, nhung: "Tra loi DUY NHAT 1 khoi ```json ...``` khop schema sau, khong giai thich" + schema gon tu `schema.model_json_schema()` rut thanh dong `{key: type}` (khong gui full JSON schema). Khong dung ky tu dau `/`. Loc URL. Muse giu ngu canh cuoc tro chuyen (chi gom tin cua app) => prompt van phai tu du, "bo qua cuoc tro chuyen truoc".
Gioi han do dai: co file -> caption <= `caption_limit`: cat phan `<untrusted_caption>`/rea_context truoc, giu instruction+schema; khong du -> frames mode khong anh huong (caption van phai du). Text thuan > 4000 ky tu -> `AIError("prompt too long for muse_tg")` (router sang provider ke); (tuy chon sau spike: gui .txt dinh kem neu Muse doc duoc).
Vision:
- `auto`: nen video bang ffmpeg (`find_ffmpeg_binary`; <= `max_video_s`, 480p, h264 crf~30, aac 64k, `-movflags +faststart`) toi <= `max_video_mb`; neu khong dat -> frames. `frames`: dung `thumbnails` truyen vao (storyboard REA) + bo sung toi da 6 khung bang `extract_thumbnail`/ffmpeg, gui album anh (caption tren anh dau). `video`: nhu auto nhung loi neu khong nen duoc.
- Gui 1 file/album + caption trong CUNG 1 luot (bot gom album theo media_group_id).
JSON: `extract_json(text)`: uu tien khoi ```json cuoi cung; khong co -> quet cap ngoac can bang dau tien (xu ly chuoi/escape); `schema.model_validate`. Sai -> 1 retry: gui tin follow-up `VC#<id8>r1` neu ro loi pydantic (ngan), yeu cau gui lai CHI JSON; lan 2 sai -> `SchemaValidationError` (dung FR-AI-01). Retry tinh vao tran `max_requests_per_day`.
Reply tre: tin bot den sau timeout bi bo (id <= tin gui cua luot moi, nen khong lam ban luot sau, nhung cung chinh vi vay luot moi phai goi `min_id` = id tin gui cua no).

Login 1 lan: `python -m videocreator muse-login` (them nhanh subcommand trong `__main__.py` TRUOC argparse hien tai, logic o `muse_login.py`): doc `MUSE_TG_API_ID/HASH` tu secrets (hoac hoi `input`/`getpass`, luu lai), `TelegramClient(StringSession(), id, hash).start(phone=input, code_callback=input, password=getpass)`, in `me.id` + canh bao neu khac `admin` trong muse_telebot_state.json khong tim thay thi chi in; luu `MUSE_TG_SESSION` vao SecretsStore; thoat. Khong can web UI cho ma. Huong dan lay api_id/api_hash o my.telegram.org in o dau lenh. Kiem tra `0600` tren POSIX; Windows dua vao DPAPI.

## 3. Danh sach file

Moi:
- `src/videocreator/ai/muse_tg.py`: `MuseTgProvider`, prompt builder, `extract_json`, media prep (ffmpeg), classify reply notices (ham thuan, test duoc).
- `src/videocreator/ai/muse_tg_client.py`: lop Telethon mong (`exchange(text, files, timeout) -> list[str]`), poll/reaction, anh xa loi Telethon -> ngoai le AI, lock + min_gap.
- `src/videocreator/muse_login.py` + nhanh `muse-login` trong `__main__.py`.
- `tests/test_muse_tg_parse.py`, `tests/test_muse_tg_live.py`, `tests/samples/muse_tg/*.txt` (reply that ghi tu spike).
Sua:
- `ai/providers.py`: nhanh `muse_tg` (truyen `settings.ai.muse_tg`, secrets).
- `config_ai.py`: `MuseTgConfig`.
- `api/routes_settings.py`: them 2 secret vao `KNOWN_SECRET_KEYS` (`MUSE_TG_API_ID`, `MUSE_TG_API_HASH`; session hien rieng chi doc), POST `/settings/config` nhan `muse_tg_*`, POST `/settings/muse-tg/test` (to_thread -> gui `VC#ping tra loi dung 1 tu: OK`, redirect `?saved=muse_tg_ok|muse_tg_fail&detail=` ngan).
- `web/templates/settings.html`: khoi "Muse qua Telegram (muse_tg)": api_id/api_hash (qua bang secret hien co), group_id, topic_id, vision_mode, max_video_mb, trang thai session (Da dang nhap / Chua — chay `python -m videocreator muse-login`), nut Test, ghi chu rui ro ToS. Luu y: settings.html/routes_settings.py dang co thay doi chua commit (git status) -> sua chong len, khong revert.
- `pyproject.toml`: `telethon>=1.36`.
- `transfer.py`: bo `MUSE_TG_SESSION` khoi file xuat `.vcx` (hien xuat MOI secret, l.50-55). Session = toan quyen TK ca nhan; may moi => chay lai `muse-login`. Test that: export roi doc lai bundle, assert khong co key nay.
- `docs/video-creator-spec.md` (cung dang modified chua commit): s1 muc 33 (ngoai le `muse_fox` -> `muse_tg`); 8.1 them ghi chu `muse_tg` tuy chon (khong doi thu tu mac dinh); FR-AI-10 viet lai (Telegram userbot Telethon, TK ca nhan = TK admin Muse2Tele, topic rieng, 1 in-flight, video <= 20 MB nen nho, rui ro ban TK, tat mac dinh, JSON ep bang prompt + validate + 1 retry); bang s9 dong FoxProfile -> "Telegram MTProto (Telethon)"; muc 691 (S13) giu; them FR-AI-11: phien `StringSession` luu trong secrets; khong ghi log noi dung tin Muse dai >300 ky tu? (khong can).
Khong sua: `analyse.py`, `analyse_queue.py`, `job_handlers.py` (router lo; `analyse_trend_item` da truyen `thumbnails=storyboard` va co nhanh writer khi khong co video).
Khong lam: dung `muse_api.py` giu nguyen (khac provider).

## 4. Phases (nho, moi phase ket thuc test chay duoc)

Truoc phase 0 (CHU lam tay): trong FoxProfile tao profile moi (vd `VC-App`), gan proxy nuoc ngoai KHAC proxy cua profile `MuseAI` (2 TK Muse cung IP = de bi lien ket), dang nhap TK Muse thu 2 => bot tu tao topic. Kiem tra profile moi KHONG nam trong post-map AutoPost (`/settings/post-map`) va khong bi gan vao doi (`/settings/muse-team`) de bot khong tu dang bai/giao viec cho no. Bao lai ten topic.
0. Spike (0.5d, thu cong, ghi vao tests/samples/muse_tg): lay `topic_id` cua topic moi (tu `muse_telebot_state.json` -> `teams.default.topics`); chay `muse-login` tam; gui 5 tin that vao topic: text JSON, album anh, video 6s `clip1_6s.mp4`, video 15 MB, text 3500 ky tu. Ghi: reaction 👌 doc duoc khong, thoi gian, Muse co "doc" noi dung video khong, caption 1024 co du khong, Muse co bao quota khong. Cap nhat plan theo ket qua.
1. Config + secrets + providers branch + `muse_tg.py` thuan (parse/prompt/media) + `test_muse_tg_parse.py`.
2. `muse_tg_client.py` + `muse_login.py` + Test live opt-in.
3. Settings UI + route test + pyproject + spec/doc edits.
4. Bat that: them `muse_tg` vao route vision/writer cua chu (thu cong), chay 1 trend item that (`-m live`).

## 5. Tests (khong mock)

- Ham thuan tren reply THAT ghi tu Phase 0: `extract_json` (fence, fence + loi giai thich, JSON kep van ban, ngoac trong chuoi, JSON sai), loc tin ⚙️/notice, anh xa notice -> ngoai le, cat prompt theo caption_limit, loc URL, schema-line tu model that `TrendAnalysisSchema`.
- ffmpeg that: nen `tests/samples/clip1_6s.mp4` -> file <= limit, doc lai bang `probe_video`; clip > limit -> roi ve frames.
- Router that (pattern `DeterministicProvider` trong test_router.py): `build_single_provider("muse_tg")` khi chua co secret -> `ProviderAuthError`, router sang provider ke; route mac dinh khong chua `muse_tg` (assert tren `AIRoutesConfig()`).
- Live `tests/test_muse_tg_live.py`, `@pytest.mark.live`, skip neu `RUN_MUSE_TG_LIVE != "1"` hoac thieu secret/config: ping, writer JSON (`TrendAnalysisSchema`), vision frames, vision video 6s, retry JSON (prompt ep tra loi sai). FloodWait/bot offline khong test duoc that => ghi ro la chua duoc test tu dong (chap nhan).

## 6. Rui ro

- Ban/khoa TK Telegram ca nhan (userbot, gui deu dan): giam bang min_gap, cap/ngay, khong giu ket noi, khong join/gui spam; chu da chap nhan. TK nay cung la admin Muse2Tele — mat TK = mat dieu khien bot.
- Session = toan quyen TK: DPAPI; khong log; khong dua vao export config bundle (kiem tra `routes_config_bundle.py` co loai secrets khong — xem cau hoi).
- Muse chat tu do: JSON khong on dinh, doi UI/tinh cach Muse; da co validate+1 retry; ngu canh topic tich luy (them "bo qua ngu canh truoc").
- TK Muse thu 2: 2 TK cung 1 may/chu => Muse co the lien ket va khoa ca 2 neu cung IP/van tay; giam bang proxy rieng + profile FoxProfile rieng. Chu chap nhan. TK Muse thu 2 bi khoa thi TK chinh (topic 6) van nen song neu IP khac.
- Muse2Tele tu dong (AutoPost, doi, muse_auto) co the dung nham profile moi => kiem tra post-map/team truoc phase 0.
- Muse khong that su "xem" video (chi khung dau/transcript): doc ket qua Phase 0 de chon `vision_mode` mac dinh; neu kem -> frames.
- Muse IP warning (bot da co `IP_CHECK`): bot/Muse bao ve profile; neu Muse tra loi canh bao IP/dang nhap -> classify = `AIError`, khong retry.
- Tai: auto_analyse 10 item x 5 nguon x 1-3 phut serial -> han che bang `max_requests_per_day` va chu chi bat muse_tg cho vision khi chap nhan hang doi dai (job khac xep sau).
- Bot offline/chu tat Muse2Tele: khong 👀 20s -> loi nhanh, router thu provider ke.
- Telethon dong bo vs event loop FastAPI: moi goi trong thread rieng + `asyncio.run`; khong goi truc tiep tu route async.

## Cau hoi chua giai quyet

Da giai quyet (2026-11-15): Premium = khong (1024); TK login = admin; topic rieng bang TK Muse thu 2; bundle co xuat secrets => loai `MUSE_TG_SESSION`; CLI login = OK; 60/ngay = OK.

Con mo (Phase 0 tra loi):
1. Muse that su phan tich noi dung video (khong chi khung dau)? Quyet dinh `vision_mode` mac dinh.
2. Bot reaction doc duoc tu userbot khong? Khong => fallback yen lang lam chinh.
3. Gui vao topic: `reply_to=topic_id` du chua hay can `top_msg_id` (tai lieu Telegram mau thuan).
