from PIL import Image

original_img = Image.open(r'D:\GithubProjects\hap-droid\out\pdd_llm_30\states\screen_2026-04-16_113735.jpg')

view_img = original_img.crop((12,
                                         252 ,
                                          174,
                                          369))
view_img.convert("RGB").save(r'view_screen_2026-04-16_113735.jpg')