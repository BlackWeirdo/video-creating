"""App-owned files of a Remotion session project (rewritten before every render)."""
from __future__ import annotations

from typing import Any

REMOTION_VERSION = "4.0.484"


WORKSPACE_PACKAGE: dict[str, Any] = {
    "name": "videocreator-studio",
    "private": True,
    "dependencies": {
        "@remotion/cli": REMOTION_VERSION,
        "remotion": REMOTION_VERSION,
        "react": "19.2.7",
        "react-dom": "19.2.7",
    },
    "devDependencies": {"@types/react": "19.2.17", "typescript": "6.0.3"},
}


INDEX_TS = """import { registerRoot } from 'remotion';
import { Root } from './Root';

registerRoot(Root);
"""


ROOT_TSX = """import React from 'react';
import { Composition } from 'remotion';
import { FPS, HEIGHT, WIDTH } from './lib';
import { TOTAL_FRAMES } from './plan';
import { Scene } from './Scene';

export const Root: React.FC = () => (
  <Composition id="Main" component={Scene} width={WIDTH} height={HEIGHT} fps={FPS} durationInFrames={TOTAL_FRAMES} />
);
"""


# Product footage is shown untouched: no filter, no opacity < 1, no playbackRate, no cover-crop (BR-PRD-02, BR-PRD-03).
LIB_TSX = """import React from 'react';
import { interpolate, OffthreadVideo, spring, staticFile, useCurrentFrame, useVideoConfig } from 'remotion';

export const WIDTH = 1080;
export const HEIGHT = 1920;
export const FPS = 30;
export const SAFE = { top: __SAFE_TOP__, bottom: __SAFE_BOTTOM__, right: __SAFE_RIGHT__ };
export const FONT_FAMILY = 'Be Vietnam Pro';

export const sec = (seconds: number): number => Math.round(seconds * FPS);

export const FontFace: React.FC = () => (
  <style>{`@font-face { font-family: '${FONT_FAMILY}'; font-weight: 700; src: url('${staticFile('BeVietnamPro-Bold.ttf')}') format('truetype'); }`}</style>
);

export const ProductShot: React.FC<{ file: string; startS: number }> = ({ file, startS }) => (
  <OffthreadVideo
    src={staticFile(file)}
    startFrom={sec(startS)}
    muted
    style={{ position: 'absolute', left: 0, top: 0, width: WIDTH, height: HEIGHT, objectFit: 'contain' }}
  />
);

export const Subtitle: React.FC<{ text: string; style?: React.CSSProperties }> = ({ text, style }) => {
  if (!text.trim()) return null;
  return (
    <div
      style={{
        position: 'absolute',
        left: 60,
        right: Math.round(WIDTH * SAFE.right),
        bottom: Math.round(HEIGHT * SAFE.bottom),
        textAlign: 'center',
        fontFamily: `'${FONT_FAMILY}'`,
        fontWeight: 700,
        fontSize: 56,
        lineHeight: 1.25,
        color: '#fff',
        textShadow: '0 0 6px #000, 0 2px 4px #000, 0 0 2px #000',
        ...style,
      }}
    >
      {text}
    </div>
  );
};

export const HookTitle: React.FC<{ text: string; style?: React.CSSProperties }> = ({ text, style }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  if (!text.trim()) return null;
  const enter = spring({ frame, fps, config: { damping: 14, stiffness: 170 } });
  const translateY = interpolate(enter, [0, 1], [38, 0]);
  const scale = interpolate(enter, [0, 1], [0.92, 1]);
  return (
    <div
      style={{
        position: 'absolute',
        left: 60,
        right: Math.round(WIDTH * SAFE.right),
        top: Math.round(HEIGHT * SAFE.top) + 48,
        display: 'flex',
        justifyContent: 'center',
      }}
    >
      <div
        style={{
          backgroundColor: 'rgba(10, 10, 10, 0.62)',
          borderRadius: 22,
          padding: '20px 30px',
          textAlign: 'center',
          fontFamily: `'${FONT_FAMILY}'`,
          fontWeight: 700,
          fontSize: 64,
          lineHeight: 1.2,
          color: '#FFFFFF',
          textShadow: '0 2px 8px rgba(0, 0, 0, 0.85)',
          transform: `translateY(${translateY.toFixed(1)}px) scale(${scale.toFixed(3)})`,
          ...style,
        }}
      >
        {text}
      </div>
    </div>
  );
};

export const KeywordCallout: React.FC<{ text: string; style?: React.CSSProperties }> = ({ text, style }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  if (!text.trim()) return null;
  const enter = spring({ frame, fps, config: { damping: 16, stiffness: 180 } });
  const translateX = interpolate(enter, [0, 1], [-44, 0]);
  return (
    <div
      style={{
        position: 'absolute',
        left: 60,
        top: Math.round(HEIGHT * SAFE.top) + 28,
        maxWidth: WIDTH - 60 - Math.round(WIDTH * SAFE.right),
        backgroundColor: 'rgba(15, 15, 15, 0.72)',
        border: '2px solid rgba(255, 255, 255, 0.85)',
        borderRadius: 16,
        padding: '14px 24px',
        fontFamily: `'${FONT_FAMILY}'`,
        fontWeight: 700,
        fontSize: 44,
        lineHeight: 1.22,
        color: '#FFF8E7',
        transform: `translateX(${translateX.toFixed(1)}px)`,
        ...style,
      }}
    >
      {text}
    </div>
  );
};

export const KineticSubtitle: React.FC<{
  text: string;
  durationFrames?: number;
  style?: React.CSSProperties;
}> = ({ text, durationFrames = 60, style }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const words = text.trim().split(/\\s+/).filter(Boolean);
  if (words.length === 0) return null;
  const total = Math.max(12, durationFrames);
  const activeIdx = Math.min(words.length - 1, Math.floor((frame / total) * words.length));
  const pop = spring({ frame: frame % Math.max(4, Math.floor(total / words.length)), fps, config: { damping: 14, stiffness: 200 } });
  const activeScale = interpolate(pop, [0, 1], [0.95, 1.06]);
  return (
    <div
      style={{
        position: 'absolute',
        left: 60,
        right: Math.round(WIDTH * SAFE.right),
        bottom: Math.round(HEIGHT * SAFE.bottom) + 20,
        textAlign: 'center',
        fontFamily: `'${FONT_FAMILY}'`,
        fontWeight: 700,
        fontSize: 56,
        lineHeight: 1.28,
        textShadow: '0 0 8px #000, 0 2px 6px #000',
        ...style,
      }}
    >
      {words.map((word, idx) => (
        <span
          key={`${idx}-${word}`}
          style={{
            display: 'inline-block',
            marginRight: 12,
            color: idx <= activeIdx ? (idx === activeIdx ? '#FFE082' : '#FFFFFF') : 'rgba(255, 255, 255, 0.72)',
            transform: idx === activeIdx ? `scale(${activeScale.toFixed(3)})` : 'scale(1)',
          }}
        >
          {word}
        </span>
      ))}
    </div>
  );
};
"""


REMOTION_CONFIG_TS = """import { Config } from '@remotion/cli/config';

Config.setVideoImageFormat('jpeg');
Config.setOverwriteOutput(true);
Config.setChromiumOpenGlRenderer('angle');
Config.setConcurrency(2);
"""


TSCONFIG_JSON = """{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "Bundler",
    "jsx": "react-jsx",
    "strict": true,
    "skipLibCheck": true,
    "esModuleInterop": true,
    "noEmit": true,
    "lib": ["DOM", "ES2022"]
  },
  "include": ["src"]
}
"""
