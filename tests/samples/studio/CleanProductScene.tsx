import React from 'react';
import {AbsoluteFill, OffthreadVideo, Sequence, staticFile} from 'remotion';

export const CleanProductScene: React.FC = () => {
  return (
    <AbsoluteFill style={{backgroundColor: '#000000'}}>
      <Sequence from={0} durationInFrames={90}>
        <OffthreadVideo
          src={staticFile('clip1_6s.mp4')}
          playbackRate={1}
          style={{width: 1080, height: 1920, opacity: 1}}
        />
      </Sequence>
    </AbsoluteFill>
  );
};
