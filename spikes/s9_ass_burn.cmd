@echo off
rem S9: burn Vietnamese ASS subtitles with libass + Be Vietnam Pro.
rem Run from anywhere; it switches to this folder so the subtitles filter
rem only sees relative paths (the repo path contains a space and a drive colon).
setlocal
cd /d "%~dp0"
if not exist out mkdir out

ffmpeg -hide_banner -y -f lavfi -i "color=c=0x303030:s=1080x1920:r=30:d=6" ^
  -f lavfi -i "anullsrc=r=48000:cl=stereo" -shortest ^
  -vf "subtitles=s9_test.ass:fontsdir=vendor/fonts" ^
  -c:v libx264 -pix_fmt yuv420p -c:a aac -b:a 128k out\s9_burn.mp4
if errorlevel 1 exit /b 1

ffmpeg -hide_banner -y -ss 1 -i out\s9_burn.mp4 -frames:v 1 -update 1 out\s9_frame_1.png
ffmpeg -hide_banner -y -ss 3 -i out\s9_burn.mp4 -frames:v 1 -update 1 out\s9_frame_2.png
ffmpeg -hide_banner -y -ss 5 -i out\s9_burn.mp4 -frames:v 1 -update 1 out\s9_frame_3.png
