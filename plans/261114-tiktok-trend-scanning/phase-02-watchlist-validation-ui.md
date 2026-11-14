# Phase 02: Kiểm tra đầu vào watchlist + giao diện

## Context links

- Plan cha: [plan.md](plan.md)
- Phụ thuộc: [phase 01](phase-01-migration-adapter-config.md) (cần nguồn `tiktok` đã đăng ký và `normalise_tiktok_handle`)
- Docs: [scout 01](scout/scout-01-trend-pipeline-touchpoints.md) dòng `routes_trends.py:79-100`, `watchlist.html:55-58`

## Overview

- Ngày: 2026-11-14
- Mô tả: `/watchlist/add` từ chối cặp nguồn/loại sai bằng lỗi 400 dễ đọc; trang Watchlist có lựa chọn TikTok, gợi ý định dạng, ô "Loại" đổi theo nguồn.
- Ưu tiên: P1
- Trạng thái triển khai: chưa bắt đầu
- Trạng thái review: chưa review

## Key Insights

- Hiện `/watchlist/add` chèn thẳng `source`/`kind`; cặp sai làm vỡ CHECK -> lỗi 500 khó hiểu. Sau migration 010, `tiktok` + `keyword` sẽ qua được CHECK nhưng không adapter nào xử lý -> phải chặn ở route.
- `kinds` thật của các adapter: youtube `keyword, account`; ig_discovery `account`; ad_library `keyword, page`; ig_hashtag `hashtag`; tiktok `account`. Test sẵn có (`tests/test_rank.py:81-95`) gửi `youtube`+`keyword` và `ad_library`+`keyword` -> vẫn hợp lệ.
- Trang `/trends` dựng nút lọc từ `build_trend_sources` (`routes_trends.py:132-133`, `trends.html:25`) -> nút `tiktok` tự xuất hiện, không cần sửa. Cột số liệu dùng `views/likes/comments` -> hiển thị đúng luôn.
- Thẻ Telegram (`tg/messages.py:59-64`) in `source` + `url` chung, không giả định YouTube -> không sửa.

## Requirements

- Kiểm tra theo thứ tự, sai thì dừng, HTTP 400:
  1. giá trị rỗng (đã có);
  2. `source` không có trong `build_trend_sources` -> `Nguồn '{source}' không được hỗ trợ.`;
  3. `kind` không thuộc `adapter.kinds` -> `Nguồn {source} chỉ nhận loại: {kinds}.`;
  4. `source == "tiktok"`: `normalise_tiktok_handle(value)`; `ValueError` -> lấy nguyên câu của nó.
- Lỗi hiển thị ngay trên trang Watchlist (khung đỏ), mã 400, không phải JSON thô.
- Thành công giữ nguyên hành vi: chèn hoặc bật lại, chuyển về `/watchlist?msg=added`.
- Giao diện: thêm `<option value="tiktok">TikTok — tài khoản (tiktok)</option>`; một dòng gợi ý; ô "Loại" chỉ hiện các loại hợp lệ của nguồn đang chọn.

## Architecture

`routes_trends.py`: tách phần dựng trang thành hàm dùng chung để route thêm có thể trả lại trang kèm lỗi.

```python
def _render_watchlist(request, *, msg=None, error=None, status_code=200) -> HTMLResponse: ...
    # context cũ + "error": error + "source_kinds": {name: list(src.kinds)}

@router.post("/watchlist/add")
async def add_watch_item_route(...):
    sources = build_trend_sources(paths, request.app.state.secrets)
    adapter = sources.get(src)
    if adapter is None: return _render_watchlist(request, error=..., status_code=400)
    if kind not in adapter.kinds: return _render_watchlist(request, error=..., status_code=400)
    if src == "tiktok":
        try: clean_val = normalise_tiktok_handle(clean_val)
        except ValueError as exc: return _render_watchlist(request, error=str(exc), status_code=400)
```

Kiểu trả về của route đổi thành `Response` (vừa redirect vừa HTML). Kiểm tra giá trị rỗng giữ `HTTPException(400)` như cũ để không đổi hành vi đang có.

`watchlist.html`:
- `{% if error %}<div class="alert alert-error">{{ error }}</div>{% endif %}` (kiểm tra tên class lỗi có sẵn trong CSS; không có thì dùng class cảnh báo đang có, không thêm CSS mới nếu tránh được).
- Gợi ý dưới ô giá trị: `TikTok: nhập @tenkenh hoặc link trang cá nhân. Chỉ theo dõi được tài khoản; TikTok không cho quét theo hashtag hay từ khoá.`
- JS nhỏ trong trang (không thư viện): `const KINDS = {{ source_kinds|tojson }}`; khi đổi `#source` thì ẩn/vô hiệu các `<option>` của `#kind` không thuộc `KINDS[source]` và chọn loại hợp lệ đầu tiên. JS chỉ để tiện; máy chủ mới là nơi quyết định.

## Related code files

Sửa:
- `src/videocreator/api/routes_trends.py` (`watchlist_page`, `add_watch_item_route`, hàm `_render_watchlist`)
- `src/videocreator/web/templates/watchlist.html`
- `tests/test_trends_tiktok.py` (thêm test route)

Không sửa: `trends.html`, `scan.py`, `tests/test_rank.py`.

## Implementation Steps

1. Đọc `routes_trends.py`, `watchlist.html`, file CSS (tìm class alert lỗi sẵn có).
2. Tách `_render_watchlist`; `watchlist_page` gọi lại nó (kết quả trang không đổi).
3. Thêm 3 bước kiểm tra vào `add_watch_item_route`.
4. Sửa template: option TikTok, khung lỗi, dòng gợi ý, JS lọc loại.
5. Test (`TestClient`, SQLite thật, `@pytest.mark.local`):
   - `tiktok` + `account` + `https://www.tiktok.com/@TiffanyAndCo?lang=en` -> 200 sau redirect, DB có đúng 1 dòng `value == "@tiffanyandco"`; gửi lại `@tiffanyandco` -> vẫn 1 dòng (UNIQUE + chuẩn hoá).
   - `tiktok` + `keyword` -> 400, thân trang có `chỉ nhận loại`, DB không thêm dòng.
   - `tiktok` + `account` + `#silver` -> 400, có `không hợp lệ`.
   - `source=facebook` -> 400, có `không được hỗ trợ`.
   - `youtube` + `hashtag` -> 400 (trước đây lọt vào DB rồi không bao giờ quét đúng).
   - `youtube` + `keyword`, `ad_library` + `keyword` -> vẫn thành công.
   - GET `/watchlist` -> có `value="tiktok"` và dòng trạng thái nguồn `tiktok`.
6. Chạy `tests/test_rank.py` + `tests/test_trends_tiktok.py`.
7. Mở trang thật trên trình duyệt: đổi nguồn, xem ô loại đổi theo; thử gõ sai để thấy khung lỗi.

## Todo list

- [ ] `_render_watchlist`
- [ ] 3 bước kiểm tra + chuẩn hoá handle
- [ ] Template: option, lỗi, gợi ý, JS
- [ ] Test route (7 ca)
- [ ] `test_rank.py` vẫn xanh
- [ ] Xem bằng mắt trên trình duyệt

## Success Criteria

- Không còn đường nào từ giao diện tạo được mục `tiktok` có loại khác `account` hoặc giá trị không phải `@handle`.
- Cặp nguồn/loại sai của MỌI nguồn trả 400 kèm câu tiếng Việt, không còn lỗi 500.
- Các mục watchlist đang có (1 mục YouTube thật) vẫn hiện, bật/tắt/xoá bình thường.

## Risk Assessment

- Dòng dữ liệu cũ có cặp nguồn/loại sai (nhập trước khi có kiểm tra): không bị đụng; khi quét adapter tự xử lý như hiện nay. Không viết migration dọn dữ liệu (YAGNI).
- Mục `tiktok` đến từ file nhập cấu hình (`.vcx`) với giá trị chưa chuẩn hoá: `fetch` chuẩn hoá lại, sai thì báo lỗi cấp tài khoản.
- Đổi chữ ký route có thể làm lệch test sẵn có -> chạy `test_rank.py` ngay.
- Ước lượng 2–3 giờ; rủi ro trượt thấp.

## Security Considerations

- `error` hiển thị qua Jinja (tự escape); thông báo lặp lại `source` người dùng gõ -> không dùng `|safe`.
- `source_kinds|tojson` là dữ liệu của máy chủ, không phải của người dùng.
- Trang vẫn sau lớp xác thực sẵn có của app; không thêm đường công khai.

## Next steps

- Phase 03: dán link video (giao diện + Telegram).
