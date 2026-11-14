import React from 'react';
import {AbsoluteFill, OffthreadVideo, staticFile} from 'remotion';

export const DirtyProductScene: React.FC = () => {
  return (
    <AbsoluteFill>
      <OffthreadVideo
        src={staticFile('clip1_6s.mp4')}
        playbackRate={1.25}
        style={{
          filter: 'contrast(1.3) saturate(1.4)',
          mixBlendMode: 'multiply',
          opacity: 0.85,
        }}
      />
    </AbsoluteFill>
  );
};
