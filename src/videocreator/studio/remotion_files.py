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


# Product footage is shown untouched: no filter, no opacity, no playbackRate, no cover-crop (BR-PRD-02, BR-PRD-03).
LIB_TSX = """import React from 'react';
import { OffthreadVideo, staticFile } from 'remotion';

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

export const Subtitle: React.FC<{ text: string; style?: React.CSSProperties }> = ({ text, style }) => (
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
