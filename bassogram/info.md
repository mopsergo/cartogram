

ffmpeg -framerate 12 -pattern_type glob -i 'cartogram_macroarea/macroarea_cartogram_*_withcountries.png' \
  -vf scale=1920:-2 -pix_fmt yuv420p cartogram_macroarea/animation.mp4