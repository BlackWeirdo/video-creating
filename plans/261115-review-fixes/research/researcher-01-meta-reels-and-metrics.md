# Research 01: Meta Page Reels API, Idempotency, Metrics, TikTok Inbox

Date: 2026-11-15. Budget: 4 tool calls, so coverage is partial. Items marked UNVERIFIED need a live check.

## Sources
- Meta Reels publishing guide: https://developers.facebook.com/docs/video-api/guides/reels-publishing (fetched, summarised by model)
- TikTok Content Posting API, upload guide: https://developers.tiktok.com/docs/en/content-posting-api-get-started-upload-content (search snippet only)
- TikTok Direct Post reference: https://developers.tiktok.com/docs/en/content-posting-api-reference-direct-post (search result only, not opened)
- Third-party TikTok guide: https://kineclip.com/blog/tiktok-inbox-draft-publishing-explained-2026/ (search result only)

## 1. Reels publishing flow (Page)

Graph version in doc examples: v27.0. Pin the version in code. Check the current default before shipping.

Prereqs:
- Page token from a user with the `CREATE_CONTENT` task on the Page.
- Permissions: `pages_show_list`, `pages_read_engagement`, `pages_manage_posts`.
- Privacy: only Public for Page reels.

Steps:
1. Start: `POST https://graph.facebook.com/v27.0/{page_id}/video_reels` with `upload_phase=start`. Returns `video_id` and `upload_url` (`https://rupload.facebook.com/video-upload/{video_id}`).
2. Upload: `POST https://rupload.facebook.com/video-upload/{video_id}`.
   - Headers: `Authorization: OAuth {page_token}`, `offset: 0`, `file_size: <bytes>`, `file_url: <public https URL>`.
   - Hosted-file rules: http/https only. No auth-protected URLs. Must allow the `facebookexternalhit` user agent. fbcdn URLs are rejected.
   - R2 public URL should meet these rules. Test with a real R2 URL.
   - Local binary upload is also allowed (`application/octet-stream`).
   - Success: `{"success": true}`.
   - The doc does not describe a separate "transfer" phase. Your plan's "transfer" wording is not in the doc.
3. Finish: `POST https://graph.facebook.com/v27.0/{page_id}/video_reels` with `video_id`, `upload_phase=finish`, `video_state=PUBLISHED`, `description` (hashtags allowed), optional `title`, `place`, `is_ai_generated` (default false).
   - Success: `{"success": true}`. No post id or permalink in response.

Video spec (from doc):
- Duration 3–90 s. Max 60 s if published as a Page story.
- 9:16. Min 540x960. Recommended 1080x1920.
- 24–60 fps, constant, progressive.
- MP4 recommended. H.264 or H.265 (VP9/AV1 also supported).
- Audio AAC-LC, 48 kHz, stereo, 128 kbps+.
- File size limit: not stated.

Limits:
- 30 API-published posts per rolling 24 h on `video_reels`. App should enforce this itself.
- 10 collaborator invites per Page per 24 h.

Error codes: 100 missing param; 1363040 aspect; 1363127 resolution; 1363128 duration; 1363129 fps.

## 2. Status and permalink

- Status: `GET https://graph.facebook.com/v27.0/{video_id}?fields=status`
- `video_status` values: `uploading`, `upload_complete`, `processing`, `ready`, `error`, `expired`, `upload_failed`.
- Phase objects:
  - `uploading_phase`: `status`, `bytes_transfered` (sic, Meta's spelling), `source_file_size`, `errors`.
  - `processing_phase`: `status`, `error`.
  - `publishing_phase`: `status`, `publish_status` (`draft`, `scheduled`, `published`, `error`), `publish_time`.
  - Phase `status`: `not_started`, `in_progress`, `completed` (some examples use `complete`), `error`.
- Permalink / post id: not in the publish response. Doc suggests listing via `GET /{page_id}/video_reels` (returns `id`, `updated_time`, `description`). Permalink field not confirmed. UNVERIFIED: request `permalink_url` on the video node.

## 3. Idempotency and duplicate prevention

Doc has no idempotency key and no dedupe guidance. Recommended app-side pattern:

1. Persist `video_id` (and `page_id`, job id) to DB right after `start` succeeds, before upload.
2. Upload: resume with `offset = bytes_transfered` from status on interrupt. Restart from `start` only if re-upload fails.
3. Finish call timeout or unknown result:
   - Do NOT call `start` again.
   - `GET /{video_id}?fields=status`.
   - If `publishing_phase.publish_status == published` (or a post exists in `GET /{page_id}/video_reels`), mark done. No retry.
   - If not published, retry `finish` with the same `video_id`.
4. Cap retries. Store state so a restart does not re-run `start`.
5. Count against the 30/24 h limit only after a `start` succeeds.

Caveat: behaviour of re-sending `finish` on an already-published video is UNVERIFIED. The status check guards against it.

Current code issue: `POST /{page_id}/videos` retry on timeout can double-post. Switching to the 3-step flow with the status check above removes that risk.

## 4. Metrics (Page Reels)

- Doc does not list reel metrics. It links to the Video Insights reference (not opened).
- `blue_reels_play_count`, `post_video_likes_by_reaction_type`, `post_video_social_actions`: names are from memory/prior knowledge. UNVERIFIED for reels. Confirm against the Page Video Insights reference.
- Permission: doc lists `pages_read_engagement` for reel work. `read_insights` is not in the reels doc. UNVERIFIED whether reel insights need `read_insights` or only `pages_read_engagement`. Check the insights reference.
- Insights are read via `GET /{video_id}/video_insights?metric=...` (UNVERIFIED path).

## 5. TikTok inbox endpoint and caption

- Inbox init: `POST https://open.tiktokapis.com/v2/post/publish/inbox/video/init/`.
- Official example body has `source_info` only. No `post_info` (title/caption/privacy) block.
- Third-party guide: caption and privacy are set by the creator in the TikTok app for uploads.
- Conflicting source: one provider doc says `title` is kept for UPLOAD method. Treat as unresolved.
- Direct Post (`/v2/post/publish/video/init/`) accepts `post_info.title`. Different flow, needs app audit for public posting.
- Result: caption cannot be set via inbox init (per official example). User must paste caption manually in the TikTok app. Matches the request, but confirm with a live test call (400 vs ignored).
- Inbox drafts report `SEND_TO_USER_INBOX` status once delivered.

## Recommendations (KISS/YAGNI)
- Replace `POST /{page_id}/videos` with the 3-step Reels flow. Keep `description` for caption.
- Add a `video_id` checkpoint and a status-first retry, as above. No new infra.
- Pin Graph version. Enforce 30 posts/24 h in app.
- Validate MP4 (9:16, 3–90 s, 24–60 fps, AAC 48 kHz) before `start` to avoid codes 1363040–1363129.
- Skip insights until a real need exists (YAGNI). Verify metric names first.

## Unresolved questions
1. Does re-sending `upload_phase=finish` on an already published video return an error or duplicate? Need a test.
2. Exact permalink field for a reel (`permalink_url` on video node?). Not verified.
3. Reel insights metric names and whether `read_insights` is required. Not verified.
4. File size limit for reels upload. Not stated.
5. Is `file_url` upload from R2 accepted given the `facebookexternalhit` UA rule? Live test needed.
6. TikTok inbox: does passing `title` error or get ignored? Official reference not opened; sources conflict.
7. Graph API version currently recommended (doc shows v27.0). Confirm.
