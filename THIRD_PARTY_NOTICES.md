# Third-Party Open-Source Notices — Video Creator V2

Video Creator V2 bundles or integrates the following open-source projects and external runtimes under their respective licenses:

1. **FreeCut Video Editor** (`walterlow/freecut`)
   - License: MIT License
   - Usage: Embedded MIT browser-based multi-track timeline editor served via `/freecut` and `/api/editor/*` bridge.

2. **Next.js & React** (`vercel/next.js`, `facebook/react`)
   - License: MIT License
   - Usage: Standalone desktop Studio web interface (`web-next/`).

3. **React Flow (`@xyflow/react`)** (`xyflow/xyflow`)
   - License: MIT License
   - Usage: Visual drag-and-drop Workflow Node DAG canvas (`/workflows`).

4. **Lucide React, Tailwind CSS, Radix UI Primitives, cmdk, sonner & next-themes**
   - Licenses: ISC / MIT Licenses.

5. **FastAPI, Uvicorn, Pydantic, APScheduler, Cryptography, yt-dlp**
   - Licenses: MIT, BSD-3-Clause, Apache-2.0, Unlicense (`yt-dlp`).

6. **FFmpeg / FFprobe** (`Gyan.FFmpeg` / `FFmpeg.org`)
   - License: LGPL / GPL (invoked exclusively as external CLI subprocess binaries; source and license notices available via upstream FFmpeg project).

7. **Node.js 24 LTS & Be Vietnam Pro Font**
   - Licenses: MIT (`Node.js`), SIL Open Font License 1.1 (`Be Vietnam Pro` in `src/videocreator/assets/fonts/`).

8. **On-Demand AI Models & CPU Inference Libraries**
   - **Faster-Whisper** (`Systran/faster-whisper`): MIT License.
   - **UVR MDX-Net (`Kim_Vocal_2.onnx`)**: MIT License.
   - **VieNeu-TTS v3 Nano ONNX** (`pnnbao97/VieNeu-TTS` / `pnnbao-ump/VieNeu-TTS-v3-Nano`): Apache-2.0 License.
   - **RapidOCR / PaddleOCR PP-OCRv4 & LaMa ONNX** (`RapidAI/RapidOCR`, `Carve/LaMa-ONNX`): Apache-2.0 License.
   - **3D-Speaker CAM++ ONNX** (`modelscope/3D-Speaker`): Apache-2.0 License.
   - **Rembg U2Net** (`danielgatis/rembg`): MIT / Apache-2.0 License.
   - **NLLB-200 Distilled 600M (`JustFrederik/nllb-200-distilled-600M-ct2-int8` / Meta AI)**: **CC-BY-NC-4.0 (Non-Commercial)** — optional on-demand offline fallback model only; commercial channels should configure primary AI translator routes (Gemini/Claude).

