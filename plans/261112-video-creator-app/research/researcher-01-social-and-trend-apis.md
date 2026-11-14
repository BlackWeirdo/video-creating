# Research: Social & Trend APIs (2026-11-12)

Phạm vi: 7 điểm trong brief. Đã tra 5 trang docs chính thức (5 call). Điểm không có trong trang đã tra → "chưa xác nhận". Kiến thức cũ không kiểm chứng cũng ghi "chưa xác nhận".

## Tóm tắt verdict

1. Meta posting: role-based cho tài khoản của mình có thể không cần App Review, nhưng chưa xác nhận. Token lifetime chưa xác nhận.
2. IG: có resumable upload, nhưng chỉ cho app dùng Facebook Login for Business. Các trường hợp khác phải có public URL (R2). Spec video chưa xác nhận.
3. Localhost redirect: chưa xác nhận cho cả Meta, Threads, TikTok.
4. TikTok unaudited: chỉ private. Direct Post dùng được với scope `video.publish`. Inbox/draft endpoint chưa xác nhận.
5. Business Discovery: có like/comments/view, `media_url` bị ẩn với video có nhạc bản quyền. Không dùng làm nguồn file video.
6. Ad Library: chỉ trả quảng cáo có reach EU (xác nhận). Video file URL và identity verification chưa xác nhận.
7. YouTube: quota mặc định 10.000 units/ngày. Mâu thuẫn về giá `search.list` (1 hay 100 units), phải kiểm tra lại.

---

## 1. Meta: quyền, Live mode, token

**Verdict:** Chưa xác nhận App Review có cần hay không. Docs IG Content Publishing không nói về App Review hay Live mode.

- Permission (Facebook Login for Business): `instagram_basic`, `instagram_content_publish`, `pages_read_engagement`.
- Permission (Instagram Login): `instagram_business_basic`, `instagram_business_content_publish`.
- Cả hai cần Advanced hoặc Standard Access. Nếu role qua Business Manager: thêm `ads_management`, `ads_read`.
- Loại token: FLB → Business Integration System User token; IG Login → Instagram User token; Facebook Login → Page token.
- Token lifetime và refresh: chưa xác nhận. Kiến thức cũ (chưa kiểm chứng): user token dài hạn ~60 ngày, Page token lấy từ user token dài hạn.
- Threads API: chưa xác nhận (không tra). Live mode với bài đăng public: chưa xác nhận.
- Nguồn: https://developers.facebook.com/docs/instagram-platform/content-publishing

## 2. IG/Threads: public URL hay upload trực tiếp; spec; giới hạn

**Verdict:** IG chỉ chắc chắn có public URL. Resumable upload chỉ cho FLB. Threads chưa xác nhận.

- Public URL: `POST /<IG_ID>/media` với `video_url`. File phải public tại thời điểm publish.
- Resumable: `POST /<IG_ID>/media` với `upload_type=resumable`, sau đó upload tới `https://rupload.facebook.com/ig-api-upload/<VER>/<CONTAINER_ID>` (header `file_url` hoặc `offset` + `file_size`). Chỉ cho app dùng Facebook Login for Business.
- Trạng thái: `GET /<CONTAINER_ID>?fields=status_code`.
- Reels: `media_type=REELS`. Kiểm tra `media_product_type` để nhận diện Reel.
- Giới hạn: 100 bài API/24h (rolling). Mục carousel ghi 50/24h, mâu thuẫn, cần kiểm tra. Xem usage: `GET /<IG_ID>/content_publishing_limit`.
- Spec video (aspect, duration, size, codec, fps): chưa xác nhận. Trang không nêu. Kiến thức cũ: 9:16, MP4/MOV, H.264, chưa kiểm chứng.
- Threads video: chưa xác nhận (không tra).
- Hệ quả: nếu dùng IG Login (không FLB) → bắt buộc R2/VPS phục vụ file public.
- Nguồn: https://developers.facebook.com/docs/instagram-platform/content-publishing

## 3. OAuth redirect `http://localhost`

**Verdict:** Chưa xác nhận cho cả Meta, Threads, TikTok. Không tra được trong phạm vi này.

- Kiểm chứng ngày 1: thử đăng ký `http://localhost` trong từng portal. Nếu không được, dùng domain HTTPS (VPS hoặc Cloudflare Tunnel) làm redirect, rồi app nhận code qua domain đó.
- Ghi chú: brainstorm đã định VPS là máy chủ, nên có sẵn domain HTTPS.

## 4. TikTok Content Posting API

**Verdict:** Unaudited chỉ đăng được private. Direct Post dùng được sau khi có scope `video.publish`. Draft/inbox chưa xác nhận.

- Unaudited: "All content posted by unaudited clients will be restricted to private viewing mode." Không có giới hạn ngày/user được nêu.
- Audit: phải qua audit để bỏ giới hạn private. Thời gian xử lý chưa xác nhận.
- Direct Post:
  - `POST /v2/post/publish/creator_info/query/`: lấy privacy level và `max_video_post_duration_sec` (ví dụ 300).
  - `POST /v2/post/publish/video/init/`: `source` = `FILE_UPLOAD` hoặc `PULL_FROM_URL`.
  - `PUT` tới `upload_url` (chỉ FILE_UPLOAD).
  - `POST /v2/post/publish/status/fetch/` với `publish_id`.
- Inbox/draft: chưa xác nhận. Trang chỉ nhắc `/v2/post/publish/inbox/video/init/` như endpoint cũ. Phải tra trang upload riêng.
- Scope: `video.publish` bắt buộc. `video.upload`: chưa xác nhận.
- Spec video đầy đủ và sandbox: chưa xác nhận. Ví dụ dùng MP4 H.264.
- Nguồn: https://developers.tiktok.com/doc/content-posting-api-get-started

## 5. Instagram Business Discovery và Hashtag Search

**Verdict:** Lấy được metric (like, comments, view). `media_url` không đảm bảo, bị ẩn với video có nhạc bản quyền. Không dùng làm nguồn file video.

- Field trong sample: `id`, `comments_count`, `like_count`, `view_count`. `media_type`, `permalink`, `timestamp`, `video_views`: không liệt kê, xem IG Media reference (chưa tra).
- `media_url`: bị bỏ với video có "copyrighted or licensed audio", và Reel có chủ sở hữu tắt download.
- Permission: `instagram_basic`, `instagram_manage_insights`, `pages_read_engagement` (+ `ads_management`/`ads_read` nếu role qua Business Manager).
- Tài khoản Business/Creator bị age-gated không trả về.
- Rate limit: chưa xác nhận (trang không nêu).
- Hashtag Search: ~30 hashtag duy nhất/7 ngày (theo brainstorm, chưa xác nhận lại trong docs đã tra).
- Nguồn: https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user/business_discovery

## 6. Meta Ad Library API (`ads_archive`)

**Verdict:** Xác nhận: quảng cáo thương mại chỉ trả khi có reach EU. Các trường (reach, snapshot), video URL và verification chưa xác nhận.

- Phạm vi: `ad_reached_countries` nhận `ALL` hoặc mã ISO. Quảng cáo không reach EU chỉ trả nếu thuộc social issues, bầu cử, chính trị. Khớp với brainstorm.
- Field: trang không liệt kê (nằm ở ArchivedAd reference, chưa tra). `ad_delivery_start_time`, `ad_snapshot_url`, `eu_total_reach`: chưa xác nhận.
- Video file URL: chưa xác nhận. `ad_snapshot_url` là trang HTML, tải video là vùng xám (theo brainstorm).
- Identity verification: chưa xác nhận từ trang đã tra (brainstorm nêu có yêu cầu).
- Rate limit: không có số cụ thể. Lỗi 613 = vượt rate limit. Lỗi 190 = access token không hợp lệ.
- Nguồn: https://developers.facebook.com/docs/graph-api/reference/ads_archive

## 7. YouTube Data API v3

**Verdict:** Search Shorts được qua `search.list` + `videoDuration`. Giá quota `search.list` mâu thuẫn, cần kiểm tra trực tiếp.

- Quota mặc định: 10.000 units/ngày, dùng chung cho mọi endpoint, trừ `search.list` và `videos.insert` có giới hạn riêng 100 call/ngày.
- Giá: `search.list` = 1 unit theo tóm tắt trang. Kiến thức cũ: 100 units/call. Mâu thuẫn, chưa xác nhận. Nếu đúng 100 units: 100 search/ngày = toàn bộ 10.000 units. Cần kiểm tra lại.
- `videos.list`, `channels.list`, `playlistItems.list`: 1 unit mỗi call (đã xác nhận).
- Lọc Shorts: không có filter Shorts riêng. Dùng `videoDuration` (short) rồi kiểm tra `contentDetails.duration` qua `videos.list` (giá trị chính xác: chưa xác nhận).
- Field: `search.list` trả snippet (id, title, channel, publishedAt). `videos.list` trả statistics (viewCount, likeCount) và duration. Chưa xác nhận từ docs đã tra.
- Nguồn: https://developers.google.com/youtube/v3/determine_quota_cost

---

## Ảnh hưởng đến plan

- IG: cần R2 hoặc VPS phục vụ public URL, trừ khi chuyển sang FLB để dùng resumable.
- TikTok: nộp audit ngày 1. Chờ audit thì dùng Direct Post private hoặc draft (draft chưa xác nhận).
- Business Discovery: chỉ theo dõi metric. Không tải video từ đây.
- Ad Library: chỉ thấy quảng cáo có reach EU. Đối thủ chỉ chạy VN thì không có dữ liệu.
- YouTube: tính quota trước khi thiết kế batch quét (giả định xấu nhất 100 units/search).

## Câu hỏi chưa giải quyết

1. Meta: role-based posting có cần App Review, Live mode có cần cho post public không.
2. Token lifetime và cơ chế refresh cho Page/IG/Threads.
3. Redirect `http://localhost` có được Meta, Threads, TikTok chấp nhận không.
4. IG và Threads: spec video, daily limit Threads.
5. Giới hạn IG publish: 100 hay 50 bài/24h.
6. TikTok: thời gian audit, endpoint draft/inbox hiện tại, scope `video.upload`.
7. Ad Library: danh sách field đầy đủ, video URL, quy trình identity verification.
8. YouTube: giá `search.list` chính xác (1 hay 100 units).
9. Business Discovery: rate limit và các field media ngoài nhóm đã nêu.
