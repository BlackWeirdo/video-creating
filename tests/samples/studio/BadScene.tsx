import React from 'react';
import { AbsoluteFill, OffthreadVideo, staticFile } from 'remotion';

export const SCENE_DURATION_FRAMES = 60;

export const Scene: React.FC = () => (
  <AbsoluteFill>
    <OffthreadVideo
      src={staticFile('stock_gold_ring.mp4')}
      playbackRate={1.25}
      style={{ filter: 'contrast(1.3) saturate(1.4)', opacity: 0.85 }}
    />
  </AbsoluteFill>
);
