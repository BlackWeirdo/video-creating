import React from 'react';
import { AbsoluteFill, Sequence } from 'remotion';
import { FontFace, ProductShot, Subtitle } from './lib';
import { PLAN } from './plan';

export const Scene: React.FC = () => (
  <AbsoluteFill style={{ backgroundColor: '#000' }}>
    <FontFace />
    {PLAN.scenes.map((scene, i) => (
      <Sequence key={i} from={scene.fromFrame} durationInFrames={scene.durationFrames}>
        <ProductShot file={scene.file} startS={scene.startS} />
        {scene.text ? <Subtitle text={scene.text} /> : null}
      </Sequence>
    ))}
  </AbsoluteFill>
);
