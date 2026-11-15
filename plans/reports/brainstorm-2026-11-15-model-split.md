# Brainstorm 2026-11-15: chia model (Opus lap ke hoach, Sonnet code)

## Van de
Chu muon model manh (Opus 5.5 / Fable 5.2) len y tuong, ke hoach, kien truc; model thap hon (Sonnet 5.5, Gemini, Muse) viet code. Hoi: lam duoc khong, can lam gi.

## Kha thi (tra tai lieu Claude Code 2026-11-15)
- Subagent frontmatter `model:` nhan `sonnet|opus|haiku|fable|inherit|<model id>`. Bo trong => dung model phien chinh. https://code.claude.com/docs/en/sub-agents.md
- Lenh/skill frontmatter `model:` doi model CHI cho luot do, luot sau ve model phien. https://code.claude.com/docs/en/skills.md
- `opusplan`: Opus trong plan mode, Sonnet khi thuc thi; chi Opus/Sonnet, khong Fable. https://code.claude.com/docs/en/model-config.md
- Model ngoai Claude (Gemini) lam model Claude Code: KHONG ho tro. https://code.claude.com/docs/en/llm-gateway.md
- Muse: chat web qua Telegram, khong doc/ghi file, khong chay lenh, tin <=4096 ky tu => khong code repo duoc. Chi dung trong app (`muse_tg`: vision/writer/checker).

## Phuong an
| | Mo ta | Uu | Nhuoc |
|---|---|---|---|
| A | `/model opusplan` | 0 cau hinh | Khong Fable; `/plan`, `/fix:hard` dung subagent nen khong di qua plan mode |
| **B (chon)** | Phien chinh Sonnet; planner/brainstormer + lenh plan/brainstorm chay Opus | Khop quy trinh hien co (agent chinh code, planner lap plan); vai dong cau hinh | Lenh `/brainstorm`, `/plan` chay Opus ca luot (gom ca doc code) |
| C | Phien chinh Opus + agent implementer Sonnet | | Implementer khoi dau khong ngu canh; dieu phoi van ton Opus; phai viet lai `/cook`, `/fix:hard` |

## Quyet dinh (chu, 2026-11-15)
- Cach B, model lap ke hoach = **Opus 5.5**.
- Ghi them huong dan Gemini CLI lam tho du phong (chua cai).

## Da ap dung
- `model: opus`: `.claude/agents/planner.md`, `.claude/agents/brainstormer.md`, `.claude/commands/brainstorm.md`, `.claude/commands/plan.md`, `.claude/commands/plan/{fast,hard,two}.md`.
- Khong doi: `plan/ci.md`, `plan/cro.md` (khong phai kien truc); code-reviewer, tester, debugger, docs-manager giu `sonnet`; scout/researcher/project-manager/git-manager giu `haiku`.
- Chu phai tu dat phien chinh: `/model sonnet` (hoac `/config` dat mac dinh). Khong co file nao trong repo ep model phien.

## Cach dung hang ngay
1. Mo phien, `/model sonnet`.
2. Y tuong/kien truc: `/brainstorm ...` hoac `/plan:hard ...` (tu chay Opus luot do) => file plan trong `plans/`.
3. Code: `/code <plan>` hoac `/cook` => Sonnet doc plan, code, goi tester/code-reviewer (Sonnet).
4. Phan nhay cam (bao mat, session Telegram, tien quang cao): yeu cau review rieng bang Opus (truyen `model: opus` khi goi code-reviewer).

## Dieu kien de Sonnet code tot
- Plan phai cu the: danh sach file, buoc, test, cau hoi mo. Plan mo ho => Sonnet doan.
- Moi phase ket thuc bang test chay duoc (dang lam vay).

## Gemini CLI lam tho du phong (chua cai, chi dung khi het han muc Claude)
- Cai: Node 20+ roi `npm install -g @google/gemini-cli`; dang nhap Google lan dau khi chay `gemini`. (Kiem tra lai lenh cai o https://github.com/google-gemini/gemini-cli truoc khi cai.)
- Giao viec: chay `gemini` o thu muc repo, prompt: "Doc CLAUDE.md va plans/<plan>/phase-XX.md, lam dung phase do, chay test theo CLAUDE.md, khong commit." Co the chep noi dung CLAUDE.md sang `GEMINI.md` de Gemini tu nap quy tac.
- Rui ro: Gemini khong dung skill/hook/subagent cua `.claude/`; de lech quy tac (mock trong test, them tinh nang thua). Sau khi Gemini lam: quay lai Claude, chay `/code-review` + toan bo test truoc khi commit.
- Khong cho Claude va Gemini sua cung luc tren 1 repo.
- Luu y: dung chung gia han muc Gemini voi provider Gemini CLI trong app (route vision/writer) neu cung TK.

## Chi so thanh cong
- Plan sinh ra boi Opus du chi tiet de Sonnet code khong phai hoi lai ve kien truc.
- Test local van dat sau moi phase do Sonnet code.
- Han muc Opus tieu chu yeu o luot plan/brainstorm.

## Cau hoi mo
- Chua kiem chung thuc te tren may nay: chay thu `/plan:fast` trong phien Sonnet, xem dong trang thai/model co doi sang Opus luot do khong.
