import React from 'react';
import { AbsoluteFill, Composition, OffthreadVideo, Sequence, staticFile } from 'remotion';
import { ClipCard } from './ClipCard';

const FPS = 30;

// Same plan shape as the app's plan_json shots, resolved to files.
const SHOTS = [
  { src: 'clip2_6s.mp4', startS: 0.5, durationS: 2.0, text: 'Từng đường giũa, từng chút kiên nhẫn' },
  { src: 'clip1_6s.mp4', startS: 1.0, durationS: 3.5, text: 'Ngọn lửa nhỏ nối liền hai đầu kim loại' },
  { src: 'clip2_6s.mp4', startS: 3.0, durationS: 2.5, text: 'Đeo lên tay, mang theo cả tâm hồn' },
];
const TOTAL_FRAMES = Math.round(SHOTS.reduce((sum, s) => sum + s.durationS, 0) * FPS);

const fontFace = `@font-face { font-family: 'Be Vietnam Pro'; font-weight: 700; src: url('${staticFile('BeVietnamPro-Bold.ttf')}') format('truetype'); }`;

// Product shot: the footage frame untouched. No filter, no opacity, no playbackRate, no cover-crop.
const ProductShot: React.FC<{ src: string; startS: number }> = ({ src, startS }) => (
  <OffthreadVideo
    src={staticFile(src)}
    startFrom={Math.round(startS * FPS)}
    muted
    style={{ width: 1080, height: 1920, objectFit: 'contain' }}
  />
);

const Subtitle: React.FC<{ text: string }> = ({ text }) => (
  <div
    style={{
      position: 'absolute',
      left: 60,
      right: 130,
      bottom: 480,
      textAlign: 'center',
      fontFamily: "'Be Vietnam Pro'",
      fontWeight: 700,
      fontSize: 56,
      lineHeight: 1.25,
      color: '#fff',
      textShadow: '0 0 6px #000, 0 2px 4px #000, 0 0 2px #000',
    }}
  >
    {text}
  </div>
);

// What a Studio render would look like: full-frame footage in plan order + subtitles.
const FullFrame: React.FC = () => {
  let from = 0;
  return (
    <AbsoluteFill style={{ backgroundColor: '#000' }}>
      <style>{fontFace}</style>
      {SHOTS.map((shot, i) => {
        const frames = Math.round(shot.durationS * FPS);
        const seq = (
          <Sequence key={i} from={from} durationInFrames={frames}>
            <ProductShot src={shot.src} startS={shot.startS} />
            <Subtitle text={shot.text} />
          </Sequence>
        );
        from += frames;
        return seq;
      })}
    </AbsoluteFill>
  );
};

// The skill's ClipCard exactly as shipped, to see what it does to 9:16 footage.
const ShippedClipCard: React.FC = () => (
  <AbsoluteFill style={{ backgroundColor: '#0b0b10', alignItems: 'center', justifyContent: 'center' }}>
    <ClipCard src="clip1_6s.mp4" size={900} caption="clip1_6s.mp4" captionSize={32} />
  </AbsoluteFill>
);

export const Root: React.FC = () => (
  <>
    <Composition id="FullFrame" component={FullFrame} width={1080} height={1920} fps={FPS} durationInFrames={TOTAL_FRAMES} />
    <Composition id="ShippedClipCard" component={ShippedClipCard} width={1080} height={1920} fps={FPS} durationInFrames={60} />
  </>
);
