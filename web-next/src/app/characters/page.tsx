"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  Image as ImageIcon,
  Mic,
  Scissors,
  Square,
  Trash2,
  Upload,
  UserCheck,
  Wand2,
} from "lucide-react";
import { toast } from "sonner";
import { apiFetch, useWorkspace } from "@/lib/api";
import { SimulationBadge } from "@/components/SimulationBadge";
import { PageHeader } from "@/components/vc/PageHeader";
import { PolicyBadge } from "@/components/vc/PolicyBadge";
import { EmptyState } from "@/components/vc/StatCard";
import { Card, SectionHeading } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  FieldLabel,
  SelectBox,
  SwitchToggle,
  TextareaBox,
  TextInput,
} from "@/components/ui/form-controls";

interface CharacterRow {
  id: number;
  name: string;
  appearance_prompt: string;
  seed: number;
  voice_id: string;
  ref_image_path: string;
  cutout_image_path: string;
  cutout_simulation_flags?: string[];
}

interface AIImageRow {
  id: number;
  character_id: number | null;
  prompt: string;
  seed: number;
  aspect_ratio: string;
  is_product_shot: boolean;
  image_path: string;
  cutout_path: string;
  motion_shot_id: number | null;
  simulation_flags?: string[];
}

interface ChannelVoiceRow {
  id: number;
  name: string;
  speaker_name: string;
  character_id: number | null;
  duration_s: number;
  audio_url: string;
  voice_token: string;
}

export default function CharactersPage() {
  const { activeWorkspaceId, activeWorkspace } = useWorkspace();
  const [characters, setCharacters] = useState<CharacterRow[]>([]);
  const [images, setImages] = useState<AIImageRow[]>([]);
  const [channelVoices, setChannelVoices] = useState<ChannelVoiceRow[]>([]);

  const [charName, setCharName] = useState("");
  const [appearance, setAppearance] = useState("");
  const [seedInput, setSeedInput] = useState("778899");

  const [imgCharId, setImgCharId] = useState<number>(0);
  const [imgPrompt, setImgPrompt] = useState("");
  const [isProductShot, setIsProductShot] = useState(false);

  const [cvName, setCvName] = useState("");
  const [cvSpeaker, setCvSpeaker] = useState("");
  const [cvCharId, setCvCharId] = useState<number>(0);
  const [cvConsent, setCvConsent] = useState(false);
  const [cvFile, setCvFile] = useState<File | null>(null);
  const [recording, setRecording] = useState(false);
  const mediaRecRef = useRef<MediaRecorder | null>(null);
  const recChunksRef = useRef<BlobPart[]>([]);

  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    try {
      const [cRes, iRes, cvRes] = await Promise.all([
        apiFetch<{ characters: CharacterRow[] }>(
          `/api/v1/characters?workspace_id=${activeWorkspaceId}`
        ),
        apiFetch<{ images: AIImageRow[] }>(
          `/api/v1/images?workspace_id=${activeWorkspaceId}`
        ),
        apiFetch<{ channel_voices: ChannelVoiceRow[] }>(
          `/api/v1/channel-voices?workspace_id=${activeWorkspaceId}`
        ),
      ]);
      setCharacters(cRes.characters || []);
      setImages(iRes.images || []);
      setChannelVoices(cvRes.channel_voices || []);
      setErr("");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Lỗi tải Studio Nhân vật");
    }
  }, [activeWorkspaceId]);

  useEffect(() => {
    void load();
  }, [load]);

  const startMicRecord = async () => {
    setErr("");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      recChunksRef.current = [];
      const mr = new MediaRecorder(stream);
      mr.ondataavailable = (ev) => {
        if (ev.data.size > 0) recChunksRef.current.push(ev.data);
      };
      mr.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(recChunksRef.current, { type: "audio/webm" });
        setCvFile(new File([blob], "mc_recorded.webm", { type: "audio/webm" }));
        setMsg(
          "Đã thu xong mẫu giọng! Hãy bật xác nhận đồng ý rồi bấm Lưu Giọng Kênh."
        );
      };
      mediaRecRef.current = mr;
      mr.start();
      setRecording(true);
    } catch {
      setErr(
        "Không truy cập được Microphone — bạn có thể chọn tệp âm thanh mẫu (.wav / .mp3)."
      );
    }
  };

  const stopMicRecord = () => {
    if (mediaRecRef.current && mediaRecRef.current.state !== "inactive") {
      mediaRecRef.current.stop();
    }
    setRecording(false);
  };

  const saveChannelVoice = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr("");
    setMsg("");
    if (!cvFile) {
      setErr("Hãy thu âm bằng Mic (5–10 giây) hoặc chọn tệp âm thanh mẫu trước.");
      return;
    }
    try {
      const fd = new FormData();
      fd.append("file", cvFile);
      fd.append("name", cvName);
      fd.append("speaker_name", cvSpeaker);
      fd.append("consent_confirmed", cvConsent ? "true" : "false");
      fd.append("workspace_id", String(activeWorkspaceId));
      if (cvCharId > 0) fd.append("character_id", String(cvCharId));

      await apiFetch("/api/v1/channel-voices", { method: "POST", body: fd });
      setCvName("");
      setCvSpeaker("");
      setCvConsent(false);
      setCvFile(null);
      const m = "Đã lưu Giọng Kênh MC (VieNeu-TTS CPU) cho Workspace!";
      setMsg(m);
      toast.success(m);
      await load();
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : "Không thể lưu Giọng kênh");
    }
  };

  const createChar = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr("");
    setMsg("");
    try {
      await apiFetch("/api/v1/characters", {
        method: "POST",
        body: JSON.stringify({
          workspace_id: activeWorkspaceId,
          name: charName,
          appearance_prompt: appearance,
          seed: Number(seedInput) || undefined,
        }),
      });
      setCharName("");
      setAppearance("");
      setMsg("Đã tạo Nhân vật Cố định mới.");
      toast.success("Đã tạo nhân vật mới.");
      await load();
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : "Lỗi tạo nhân vật");
    }
  };

  const uploadCharRef = async (charId: number, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    const resp = await fetch(`/api/v1/characters/${charId}/upload-ref`, {
      method: "POST",
      body: fd,
    });
    if (!resp.ok) {
      const d = await resp.json();
      setErr(d.detail || "Lỗi tải ảnh tham chiếu");
      return;
    }
    setMsg(`Đã cập nhật ảnh tham chiếu cho Nhân vật #${charId}.`);
    await load();
  };

  const generateImg = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr("");
    setMsg("");
    try {
      await apiFetch("/api/v1/images", {
        method: "POST",
        body: JSON.stringify({
          workspace_id: activeWorkspaceId,
          character_id: imgCharId > 0 ? imgCharId : null,
          prompt: imgPrompt,
          is_product_shot: isProductShot,
          animate_to_shot: true,
        }),
      });
      setImgPrompt("");
      setMsg("Đã tạo khung cảnh + chuyển thành Shot chuyển động.");
      toast.success("Đã tạo ảnh & Shot chuyển động.");
      await load();
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : "Không thể sinh ảnh");
    }
  };

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <PageHeader
        icon={<UserCheck className="w-5 h-5" />}
        title="Nhân vật Cố định, Giọng Kênh MC & Ảnh AI"
        badges={<PolicyBadge policy={activeWorkspace?.content_policy} showDetail />}
        description="Quản lý nhân vật cố định Seed, tách nền trong suốt bằng Rembg U2Net, lưu mẫu Giọng Kênh MC 5–10 giây có xác nhận đồng ý và tạo cảnh B-roll."
      />

      {msg && (
        <div
          role="status"
          className="rounded-[11px] border border-[var(--st-emerald-bd)] bg-[var(--st-emerald-bg)] px-4 py-2.5 text-[13px] text-[var(--st-emerald-tx)]"
        >
          {msg}
        </div>
      )}
      {err && (
        <div
          role="alert"
          className="rounded-[11px] border border-[var(--st-rose-bd)] bg-[var(--st-rose-bg)] px-4 py-2.5 text-[13px] text-[var(--st-rose-tx)]"
        >
          {err}
        </div>
      )}

      <div className="grid md:grid-cols-2 gap-4">
        <Card tinted>
          <form onSubmit={createChar} className="space-y-3.5">
            <SectionHeading>Tạo Nhân vật Đồng nhất</SectionHeading>
            <div>
              <FieldLabel htmlFor="chr-name">Tên nhân vật *</FieldLabel>
              <TextInput
                id="chr-name"
                required
                value={charName}
                onChange={(e) => setCharName(e.target.value)}
                placeholder="VD: MC Bảo Ngọc"
              />
            </div>
            <div>
              <FieldLabel htmlFor="chr-app">Mô tả ngoại hình cố định</FieldLabel>
              <TextareaBox
                id="chr-app"
                rows={2}
                value={appearance}
                onChange={(e) => setAppearance(e.target.value)}
                placeholder="Trang phục, kiểu tóc, phong thái..."
              />
            </div>
            <div>
              <FieldLabel htmlFor="chr-seed">Mã Seed cố định</FieldLabel>
              <TextInput
                id="chr-seed"
                type="number"
                value={seedInput}
                onChange={(e) => setSeedInput(e.target.value)}
                className="tabular-nums"
              />
            </div>
            <Button type="submit">Tạo Nhân Vật</Button>
          </form>
        </Card>

        <Card>
          <form onSubmit={generateImg} className="space-y-3.5">
            <SectionHeading>
              <Wand2 className="w-4 h-4 text-[var(--c-icon)]" /> Sinh Cảnh Nền &amp; Shot Chuyển Động
            </SectionHeading>
            <div>
              <FieldLabel htmlFor="img-chr">Gắn nhân vật</FieldLabel>
              <SelectBox
                id="img-chr"
                value={imgCharId}
                onChange={(e) => setImgCharId(Number(e.target.value))}
              >
                <option value={0}>Không gắn nhân vật</option>
                {characters.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name} (Seed {c.seed})
                  </option>
                ))}
              </SelectBox>
            </div>
            <div>
              <FieldLabel htmlFor="img-prompt">Mô tả bối cảnh cảnh quay *</FieldLabel>
              <TextareaBox
                id="img-prompt"
                required
                rows={2}
                value={imgPrompt}
                onChange={(e) => setImgPrompt(e.target.value)}
                placeholder="VD: Bàn trưng bày ánh nắng sớm tối giản..."
              />
            </div>
            <div className="flex items-center gap-2.5">
              <SwitchToggle
                id="img-prd"
                checked={isProductShot}
                onCheckedChange={setIsProductShot}
              />
              <label
                htmlFor="img-prd"
                className="text-[12.5px] text-[var(--text-secondary)] cursor-pointer"
              >
                Cảnh có sản phẩm (chỉ cho phép ở Hybrid / Full AI)
              </label>
            </div>
            <Button type="submit" variant="secondary">
              Sinh Ảnh + Shot Chuyển Động
            </Button>
          </form>
        </Card>
      </div>

      {/* Consented MC Channel Voice */}
      <Card className="space-y-4">
        <SectionHeading>
          <Mic className="w-4 h-4 text-[var(--c-icon)]" /> Thư viện Giọng Kênh MC (Thu mẫu 5–10 giây • VieNeu CPU)
        </SectionHeading>

        <form onSubmit={saveChannelVoice} className="space-y-3.5">
          <div className="grid md:grid-cols-4 gap-3 items-end">
            <div>
              <FieldLabel htmlFor="cv-name">Tên giọng kênh *</FieldLabel>
              <TextInput
                id="cv-name"
                required
                value={cvName}
                onChange={(e) => setCvName(e.target.value)}
                placeholder="VD: Giọng Kênh Bảo Ngọc"
              />
            </div>
            <div>
              <FieldLabel htmlFor="cv-spk">Họ tên MC đồng ý *</FieldLabel>
              <TextInput
                id="cv-spk"
                required
                value={cvSpeaker}
                onChange={(e) => setCvSpeaker(e.target.value)}
                placeholder="Họ tên người thu mẫu"
              />
            </div>
            <div>
              <FieldLabel htmlFor="cv-chr">Gắn mặc định cho nhân vật</FieldLabel>
              <SelectBox
                id="cv-chr"
                value={cvCharId}
                onChange={(e) => setCvCharId(Number(e.target.value))}
              >
                <option value={0}>Dùng chung toàn Workspace</option>
                {characters.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </SelectBox>
            </div>
            <div className="flex gap-2">
              {!recording ? (
                <Button
                  type="button"
                  variant="danger"
                  onClick={() => void startMicRecord()}
                >
                  <Mic className="w-4 h-4" /> Thu Mic
                </Button>
              ) : (
                <Button type="button" variant="danger" onClick={stopMicRecord}>
                  <Square className="w-4 h-4" /> Dừng thu
                </Button>
              )}
              <label className="inline-flex min-h-[38px] items-center gap-1.5 rounded-[9px] border border-[var(--border-strong)] bg-[var(--bg-elevated)] px-3 py-1.5 text-[13px] font-semibold text-[var(--text-primary)] hover:border-[var(--c-bd)] cursor-pointer">
                <Upload className="w-4 h-4 text-[var(--c-icon)]" /> Tệp mẫu
                <input
                  type="file"
                  accept=".wav,.mp3,.m4a,.webm,.ogg"
                  className="sr-only"
                  onChange={(e) => setCvFile(e.target.files?.[0] || null)}
                />
              </label>
            </div>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-3 pt-1">
            <div className="flex items-center gap-2.5">
              <SwitchToggle
                id="cv-consent"
                checked={cvConsent}
                onCheckedChange={setCvConsent}
              />
              <label
                htmlFor="cv-consent"
                className="text-[13px] text-[var(--text-secondary)] cursor-pointer"
              >
                Xác nhận MC / chủ giọng thuộc công ty và đã đồng ý nhân bản giọng cho kênh này.
                {cvFile && (
                  <Badge tone="emerald" className="ml-2">
                    {cvFile.name}
                  </Badge>
                )}
              </label>
            </div>
            <Button type="submit" variant="emerald">
              Lưu Giọng Kênh
            </Button>
          </div>
        </form>

        {channelVoices.length > 0 && (
          <div className="grid md:grid-cols-2 gap-3 pt-2">
            {channelVoices.map((cv) => (
              <div
                key={cv.id}
                className="rounded-[11px] border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-3 space-y-2"
              >
                <div className="flex items-center justify-between gap-2">
                  <div>
                    <strong className="text-[13.5px] text-[var(--text-primary)]">
                      {cv.name}
                    </strong>{" "}
                    <span className="text-[12px] text-[var(--text-muted)] tabular-nums">
                      ({cv.speaker_name} • {cv.duration_s}s)
                    </span>
                  </div>
                  <Button
                    type="button"
                    size="icon"
                    variant="ghost"
                    aria-label={`Xóa giọng ${cv.name}`}
                    onClick={async () => {
                      await apiFetch(`/api/v1/channel-voices/${cv.id}`, {
                        method: "DELETE",
                      });
                      await load();
                    }}
                  >
                    <Trash2 className="w-4 h-4 text-rose-400" />
                  </Button>
                </div>
                {cv.audio_url && (
                  <audio controls src={cv.audio_url} className="h-8 w-full" />
                )}
              </div>
            ))}
          </div>
        )}
      </Card>

      <div className="grid md:grid-cols-2 gap-4">
        <Card className="space-y-3">
          <SectionHeading className="tabular-nums">
            Nhân vật ({characters.length})
          </SectionHeading>
          {characters.length === 0 ? (
            <EmptyState title="Chưa tạo nhân vật cố định nào" />
          ) : (
            <div className="space-y-2.5">
              {characters.map((c) => (
                <div
                  key={c.id}
                  className="rounded-[11px] border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-3.5 space-y-2"
                >
                  <div className="flex items-center justify-between gap-2">
                    <strong className="text-[14px] text-[var(--text-primary)]">
                      {c.name}
                    </strong>
                    <Badge tone="cluster" className="tabular-nums">
                      Seed {c.seed}
                    </Badge>
                  </div>
                  <div className="text-[12.5px] text-[var(--text-muted)]">
                    {c.appearance_prompt || "—"}
                  </div>
                  <div className="flex flex-wrap gap-2 items-center">
                    <label className="inline-flex min-h-[32px] items-center gap-1.5 rounded-[8px] border border-[var(--border-strong)] bg-[var(--bg-card)] px-2.5 py-1 text-[12px] font-semibold text-[var(--text-primary)] hover:border-[var(--c-bd)] cursor-pointer">
                      <Upload className="w-3.5 h-3.5 text-[var(--c-icon)]" /> Ảnh gốc
                      <input
                        type="file"
                        accept=".png,.jpg,.jpeg,.webp"
                        className="sr-only"
                        onChange={(ev) => {
                          const f = ev.target.files?.[0];
                          if (f) void uploadCharRef(c.id, f);
                        }}
                      />
                    </label>
                    {c.ref_image_path && (
                      <Button
                        type="button"
                        size="sm"
                        variant="secondary"
                        onClick={async () => {
                          await apiFetch(`/api/v1/characters/${c.id}/cutout`, {
                            method: "POST",
                          });
                          setMsg(
                            `Đã tách nền PNG (Rembg U2Net) cho nhân vật #${c.id}.`
                          );
                          await load();
                        }}
                      >
                        <Scissors className="w-3.5 h-3.5" /> Tách nền PNG
                      </Button>
                    )}
                  </div>
                  <SimulationBadge flags={c.cutout_simulation_flags} />
                </div>
              ))}
            </div>
          )}
        </Card>

        <Card className="space-y-3">
          <SectionHeading className="tabular-nums">
            <ImageIcon className="w-4 h-4 text-[var(--c-icon)]" /> Kho Ảnh Cảnh Nền ({images.length})
          </SectionHeading>
          {images.length === 0 ? (
            <EmptyState title="Chưa có ảnh cảnh nền nào" />
          ) : (
            <div className="grid sm:grid-cols-2 gap-3">
              {images.map((im) => (
                <div
                  key={im.id}
                  className="rounded-[11px] border border-[var(--border-subtle)] bg-[var(--bg-elevated)] p-3 space-y-2"
                >
                  {im.image_path && (
                    <div className="aspect-video w-full overflow-hidden rounded-[8px] bg-black">
                      <img
                        src={`/files/${im.image_path}`}
                        alt={im.prompt}
                        className="h-full w-full object-cover"
                      />
                    </div>
                  )}
                  <div className="text-[12.5px] text-[var(--text-primary)] line-clamp-2">
                    {im.prompt}
                  </div>
                  <div className="text-[11.5px] text-[var(--text-muted)] tabular-nums">
                    Seed {im.seed} • Shot: {im.motion_shot_id ?? "chưa tạo"}
                  </div>
                  <SimulationBadge flags={im.simulation_flags} />
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
