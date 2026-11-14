import { Config } from '@remotion/cli/config';

Config.setVideoImageFormat('jpeg');
Config.setOverwriteOutput(true);
Config.setChromiumOpenGlRenderer('angle');
// 8 GB RAM machine: keep the number of Chromium tabs low.
Config.setConcurrency(2);
