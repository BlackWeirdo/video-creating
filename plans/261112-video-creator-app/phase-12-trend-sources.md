# Phase 12: Nguồn xu hướng + xếp hạng

## Context links

- Plan cha: [plan.md](plan.md)
- Phụ thuộc: [phase 02](phase-02-project-skeleton.md), [phase 07](phase-07-posting-facebook-instagram.md) (token Meta); kết quả S6, S10 của [phase 01](phase-01-verification-spikes.md)
- Docs: [research 01 mục 5, 6, 7](research/researcher-01-social-and-trend-apis.md), [brainstorm mục 3.3](../reports/brainstorm-2026-11-12-video-creator.md)

## Overview

- Ngày: 2026-11-12
- Mô tả: interface `TrendSource` + 4 adapter (IG Business Discovery, IG Hashtag Search, YouTube Data API, Meta Ad Library); danh sách theo dõi; quét định kỳ; xếp hạng; trang xem kết quả.
- Ưu tiên: P2
- Trạng thái triển khai: chưa bắt đầu
- Trạng thái review: chưa review

## Key Insights

- Không nguồn nào trả "video trend theo ngành"; tất cả đều là theo dõi danh sách brand/hashtag/từ khoá do người dùng nhập.
- Business Discovery: có metric, `media_url` không đảm bảo -> chỉ dùng metric, không coi là nguồn file.
- Ad Library: chỉ quảng cáo có reach EU; không có chi tiêu; "hiệu quả" suy từ số ngày chạy + còn active + reach EU. Quyền truy cập cần xác minh danh tính (có thể chưa xong).
- YouTube: giả định xấu nhất `search.list` = 100 units -> tối đa ~80 search/ngày; `videos.list` 1 unit cho 50 id.
- Hashtag Search: ~30 hashtag/7 ngày -> danh sách hashtag phải nhỏ và cố định.
- 4 adapter trong 1 phiên là nhiều. Thứ tự làm = thứ tự giá trị/độ chắc: YouTube -> Business Discovery -> Ad Library -> Hashtag. Hết giờ thì dừng, cái còn lại bỏ.

## Requirements

- Interface:

```python
@dataclass
class TrendItem: source: str; external_id: str; url: str; author: str; caption: str
                 published_at: datetime; metrics: dict; video_url: str | None

class TrendSource(Protocol):
    name: str
    kinds: tuple[str, ...]            # loại watch item hỗ trợ: account | hashtag | keyword | page
    def fetch(self, watch: WatchItem) -> list[TrendItem]: ...
```

- Migration `002_trends.sql`: `watch_items` (id, source, kind, value, enabled), `trend_items` (id, source, external_id, url, author, caption, published_at, metrics_json, score, analysis_json, fetched_at; UNIQUE(source, external_id)), `suggestions` (tạo sẵn cho phase 13: id, trend_item_id, text, formula_json, status, created_at).
- UI: trang danh sách theo dõi (thêm/xoá/tắt), trang kết quả sắp theo điểm, lọc theo nguồn, link mở bài gốc.
- Quét: job cron 1 lần/ngày (giờ cấu hình) + nút "Quét ngay". Lỗi 1 nguồn không chặn nguồn khác.
- Điểm (đơn giản, minh bạch, cùng thang trong 1 nguồn):
  - IG/YouTube: `(like + 2*comment + view/100) / max(số giờ từ lúc đăng, 24)`.
  - Ad Library: `số ngày chạy * (1.5 nếu còn active) + log10(reach EU)`; chỉ lấy ad video chạy >= 30 ngày.
  - Xếp hạng trong từng nguồn, không trộn thang giữa các nguồn.
- Hạn mức: bộ đếm quota YouTube trong ngày và hashtag trong 7 ngày lưu DB; vượt thì bỏ qua + cảnh báo.

## Architecture

```
trends/base.py          # TrendItem, WatchItem, TrendSource
trends/youtube.py       # search.list (videoDuration=short, order=viewCount, publishedAfter) -> videos.list
trends/ig_discovery.py  # GET /{ig_id}?fields=business_discovery.username(X){media{...}}
trends/ad_library.py    # GET /ads_archive (search_page_ids | search_terms, ad_reached_countries, media_type=VIDEO)
trends/ig_hashtag.py    # ig_hashtag_search -> /{hashtag_id}/top_media
trends/rank.py          # score(item) theo nguồn
trends/scan.py          # scan_all(): lặp watch_items -> fetch -> upsert -> score
api/routes_trends.py
```

Đăng ký nguồn: dict `{name: TrendSource}`; nguồn thiếu key/quyền tự vô hiệu và hiện lý do trên UI.

## Related code files

Tạo: các file trên; `src/videocreator/migrations/002_trends.sql`, `web/templates/watchlist.html`, `web/templates/trends.html`, `tests/test_rank.py`, `tests/test_trends_live.py`.
Sửa: `scheduler.py` (job quét), `app.py`, `config.py` (`[trends]`: giờ quét, quốc gia Ad Library, số ngày nhìn lại).

## Implementation Steps

1. Migration + `base.py` + trang danh sách theo dõi.
2. `youtube.py` + bộ đếm quota.
3. `ig_discovery.py` (dùng token Meta đã có; cần thêm quyền `instagram_manage_insights`: kiểm tra, nếu thiếu thì kết nối lại).
4. `rank.py`, `scan.py`, job cron, trang kết quả.
5. `ad_library.py` (chỉ khi S6 đạt; field theo kết quả S6).
6. `ig_hashtag.py` + bộ đếm 30/7 ngày (làm cuối, cắt được).
7. Test `-m local`: `score()` trên các `TrendItem` dựng từ số liệu thật đã lưu của 1 lần quét (ghi lại vào `tests/samples/trend_items.json` từ lần chạy live đầu tiên, không bịa số); upsert không tạo trùng.
8. Test `-m live` (CẦN key YouTube, token Meta của người dùng): mỗi adapter fetch 1 watch item thật (ví dụ 1 kênh/brand trang sức lớn), khẳng định >= 1 item có đủ field bắt buộc.

## Todo list

- [ ] Migration + interface + watchlist UI
- [ ] YouTube + quota
- [ ] IG Business Discovery
- [ ] Rank + scan + cron + UI kết quả
- [ ] Ad Library (nếu S6 đạt)
- [ ] IG Hashtag (nếu còn giờ)
- [ ] Test local + live

## Success Criteria

- Nhập 5 brand + 5 từ khoá -> bấm "Quét ngay" -> trang kết quả có danh sách xếp hạng theo từng nguồn, mở được link gốc.
- Quét hằng ngày chạy 3 ngày liên tục không vượt quota, không tạo bản ghi trùng.
- Nguồn chưa có quyền (ví dụ Ad Library) hiện "chưa bật: <lý do>", không làm hỏng lần quét.

## Risk Assessment

- Xác minh Ad Library chưa xong -> adapter đó làm sau hoặc bỏ. Không chặn phase 13.
- Đối thủ chỉ chạy ở Việt Nam không có trong Ad Library: giới hạn của API, không sửa được. Không scrape.
- Quyền `instagram_manage_insights` có thể đòi App Review riêng (chưa xác nhận) -> Business Discovery/Hashtag có thể không dùng được; khi đó tuần 2 chỉ còn YouTube + Ad Library.
- Dễ trượt (1–1.5 ngày). Cắt: Hashtag trước, Ad Library sau.

## Security Considerations

- Chỉ lưu metadata công khai + link; không tải file video của người khác ở phase này.
- Key YouTube và token Meta trong secrets store.
- Tôn trọng rate limit: lỗi 613/429 -> dừng nguồn đó tới lần quét sau, không retry dồn.

## Next steps

- Phase 13 phân tích top item và sinh đề xuất.
