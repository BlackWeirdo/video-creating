# Phase 04: Chia suất đều giữa 5 nền tảng + ưu tiên bài tự chọn

## Context links

- Plan cha: [plan.md](plan.md)
- Phụ thuộc: [phase 01](phase-01-migration-adapter-config.md), [phase 03](phase-03-pasted-link-intake.md) (cờ `metrics.pinned`)
- Docs: [đặc tả](../../docs/video-creator-spec.md) `FR-TRD-04`, `FR-TRD-06`, `FR-TRD-07`, `BR-REF-01`
- Mã: `src/videocreator/trends/analyse.py:190-228`, `src/videocreator/trends/suggest.py:76-102`

## Overview

- Ngày: 2026-11-14
- Mô tả: chủ cần video xu hướng của CẢ TikTok, YouTube, Instagram, Facebook Reels và quảng cáo. Mã hiện tại chọn bài để tải và để đề xuất theo cách khiến một nền tảng có thể lấn hết. Phase này đổi cách chọn thành xoay vòng theo nền tảng.
- Ưu tiên: P1
- Trạng thái triển khai: chưa bắt đầu
- Trạng thái review: chưa review

## Key Insights

- **Tải + phân tích** (`analyse_top_trends`): duyệt nguồn theo bảng chữ cái, mỗi nguồn 3 bài; trần tải 5 file/ngày dùng chung -> nguồn đứng đầu bảng chữ cái lấy 3 suất, nguồn thứ hai 2 suất, các nguồn sau 0 suất (chỉ còn phân tích bằng chữ).
- **Đề xuất** (`make_suggestions`): lấy 6 bài điểm cao nhất TRỘN mọi nguồn. Điểm tính theo từng nguồn, không so được giữa nguồn (`FR-TRD-04`): view TikTok lớn hơn YouTube nhiều lần, điểm quảng cáo theo thang khác hẳn -> một nền tảng chiếm hết.
- Có 6 tên nguồn nhưng chỉ 5 nền tảng: `ig_discovery`, `ig_hashtag`, `instagram` (bài dán) là một.
- Trần 5 file/ngày (`BR-REF-01`) đúng bằng số nền tảng -> xoay vòng cho mỗi nền tảng 1 file/ngày mà KHÔNG phải nâng trần, không tăng thời gian máy so với hiện nay (5 x ~20 phút).
- Trần 3 đề xuất/ngày (`FR-TRD-07`) nhỏ hơn 5 nền tảng. Hai cách: giữ 3 và xoay vòng qua ngày, hoặc nâng lên 5. Kế hoạch này làm thành khoá config, mặc định 5 (cần chủ xác nhận, xem plan.md).

## Requirements

- Nhóm nền tảng (một hàm thuần, một nơi duy nhất):

| `source` | Nhóm |
|---|---|
| `tiktok` | `tiktok` |
| `youtube` | `youtube` |
| `ig_discovery`, `ig_hashtag`, `instagram` | `instagram` |
| `facebook` | `facebook` |
| `ad_library` | `ads` |
| tên lạ | chính nó |

- `analyse_top_trends`:
  1. Với mỗi nhóm: lấy các bài chưa phân tích, bài `pinned` trước, rồi theo điểm giảm dần, tối đa `top_k_per_source` bài.
  2. Xếp thứ tự xử lý xoay vòng: bài hạng 1 của từng nhóm, rồi bài hạng 2 của từng nhóm, ... Thứ tự nhóm trong một vòng: xoay theo ngày (nhóm bắt đầu = số thứ tự ngày chia dư cho số nhóm) để không nhóm nào luôn đứng cuối khi hết suất.
  3. Phần còn lại giữ nguyên: mỗi bài vẫn qua `analyse_trend_item`; trần file/ngày vẫn do `fetch_reference_video` giữ.
- `make_suggestions`:
  1. Ứng viên: với mỗi nhóm lấy tối đa 2 bài đã phân tích, chưa có đề xuất: bài `pinned` trước, rồi theo điểm. Ghép xoay vòng như trên. Tối đa 10 ứng viên (5 nhóm x 2) thay cho `LIMIT 6`.
  2. Lời nhắc cho AI thêm 1 dòng: `Chọn ý tưởng từ các nền tảng khác nhau; mỗi nền tảng tối đa 1 đề xuất trừ khi không đủ; ưu tiên mục có "pinned": true.` và thêm trường `platform`, `pinned` vào từng khối ứng viên.
  3. Sau khi AI trả về: nếu số đề xuất vượt 1/nhóm mà còn nhóm khác có ứng viên chưa dùng thì bỏ bớt đề xuất trùng nhóm (giữ cái đầu). Kiểm bằng mã, không tin lời AI.
  4. Trần/ngày đọc từ `trends.max_suggestions_per_day` (mặc định 5) thay cho số 3 viết cứng.
- Trang `/trends`: nút lọc theo 5 nhóm nền tảng (thay cho danh sách adapter), để bài dán `instagram`/`facebook` lọc được. Dòng trạng thái nguồn giữ nguyên.
- Không đổi công thức điểm (`rank.py`), không đổi bảng dữ liệu, không migration.

## Architecture

```
trends/base.py
  PLATFORM_GROUPS: dict[str, str]
  def platform_of(source: str) -> str
  def interleave(groups: dict[str, list], start: int = 0) -> list      # xoay vòng, thuần

trends/analyse.py   analyse_top_trends(): thay vòng lặp theo nguồn bằng danh sách đã xoay vòng
trends/suggest.py   make_suggestions(): thay câu SQL LIMIT 6 bằng chọn theo nhóm + lọc sau AI
config.py           TrendsConfig.max_suggestions_per_day: int = 5
api/routes_trends.py + trends.html: lọc theo nhóm (WHERE source IN (...))
```

`pinned` đọc từ `metrics_json` bằng Python sau khi truy vấn (số dòng nhỏ: vài chục tới vài trăm), không dùng hàm JSON của SQLite để khỏi phụ thuộc bản SQLite.

## Related code files

Sửa:
- `src/videocreator/trends/base.py`, `analyse.py`, `suggest.py`
- `src/videocreator/config.py`
- `src/videocreator/api/routes_trends.py`, `src/videocreator/web/templates/trends.html`
- `tests/test_suggestion_flow.py` chỉ khi test cũ khẳng định đúng hành vi "6 bài trộn nguồn" (đọc trước; nếu không thì không sửa)

Tạo:
- `tests/test_trends_fair_share.py`

Không sửa: `rank.py`, `download.py`, `scan.py`, mã Telegram.

## Implementation Steps

1. Đọc `analyse.py`, `suggest.py`, `tests/test_suggestion_flow.py`, `tests/test_tg_flows.py` để biết test nào đang dựa vào thứ tự chọn hiện tại.
2. Viết `platform_of`, `interleave` trong `base.py`.
3. Sửa `analyse_top_trends` (giữ nguyên chữ ký hàm và giá trị trả về).
4. Sửa `make_suggestions` (giữ nguyên chữ ký; tham số `max_suggestions` mặc định lấy từ config).
5. Thêm khoá config; sửa lọc trên `/trends`.
6. Test local (SQLite thật, không mạng, không mock; bước cần AI thì truyền provider thật ở test live, còn test local chỉ kiểm phần CHỌN ứng viên bằng cách tách phần đó thành hàm thuần `pick_suggestion_candidates(db_file) -> list[row]` và `order_items_for_analysis(db_file, top_k, day_index) -> list[int]`):
   - Chèn bài của 5 nhóm bằng `upsert_trend_item` với số liệu lấy từ các mẫu thật đã có (`tests/samples/trend_items.json`, mẫu TikTok, mẫu dán link) -> thứ tự phân tích: 5 bài đầu thuộc 5 nhóm khác nhau.
   - Một nhóm có điểm gấp nghìn lần nhóm khác -> vẫn chỉ chiếm 1 trong 5 vị trí đầu.
   - `ig_discovery` + `ig_hashtag` + `instagram` chỉ tính 1 nhóm.
   - Bài `pinned` điểm 0 đứng trước bài điểm cao cùng nhóm.
   - Chỉ có 2 nhóm có bài -> lấp đủ suất bằng 2 nhóm đó (không bỏ trống).
   - Đổi `day_index` -> nhóm bắt đầu đổi.
   - Lọc sau AI: danh sách 3 đề xuất cùng nhóm trong khi nhóm khác còn ứng viên -> còn 1.
   - `max_suggestions_per_day`: config cũ thiếu khoá -> 5; đã tạo đủ trong ngày -> trả `[]`.
7. Test live (`-m live`, cần quota AI): `make_suggestions` trên DB có bài đã phân tích của >= 2 nhóm -> đề xuất thuộc >= 2 nhóm.
8. Chạy `tests/test_suggestion_flow.py`, `test_tg_flows.py`, `test_tg_messages.py`, `test_rank.py`, `test_metrics.py`.

## Todo list

- [ ] Đọc mã + test hiện có
- [ ] `platform_of`, `interleave`
- [ ] `analyse_top_trends` xoay vòng
- [ ] `make_suggestions` chọn theo nhóm + lọc sau AI + trần từ config
- [ ] Lọc `/trends` theo nhóm
- [ ] Test local (8 nhóm kiểm) + live
- [ ] Test cũ liên quan xanh

## Success Criteria

- Có bài của N nền tảng -> N file tham khảo đầu tiên trong ngày thuộc N nền tảng khác nhau (N <= 5).
- Đề xuất trong ngày trải trên các nền tảng có bài; bài tự chọn (`pinned`) đã phân tích luôn nằm trong ứng viên.
- Chỉ có 1 nền tảng hoạt động (tình trạng hôm nay: chỉ YouTube) -> hành vi như cũ, không trống suất.
- Test cũ về đề xuất và Telegram vẫn xanh.

## Risk Assessment

- Đổi cách chọn làm test cũ lệch -> bước 1 đọc trước; nếu test cũ chỉ có 1 nguồn (đúng với `test_suggestion_flow.py` hiện tại: chỉ `youtube`) thì kết quả không đổi.
- Nâng trần đề xuất 3 -> 5: tăng tin nhắn Telegram và chi phí AI khi chủ bấm tạo video; lượt gọi AI tạo đề xuất vẫn là 1 lượt/lần quét. Lùi được bằng 1 dòng config.
- 10 ứng viên thay cho 6 -> lời nhắc dài hơn ~60%; vẫn nhỏ.
- Nhóm `ads` điểm theo thang riêng và bài chạy < 30 ngày có điểm 0 (bị `scan.py` loại từ lúc quét) -> không ảnh hưởng.
- Ước lượng 4–5 giờ.

## Security Considerations

- Không có đầu vào mới từ ngoài. Tham số lọc `source` trên `/trends` so với danh sách nhóm cố định, không ghép vào SQL.
- Lời nhắc AI vẫn bọc dữ liệu ngoài như cũ; cờ `pinned` do app đặt, không lấy từ nội dung video.

## Next steps

- Phase 05: bật thật các nguồn Instagram / Facebook / quảng cáo để các nhóm này có bài tự động.
