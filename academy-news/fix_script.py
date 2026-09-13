with open('send_neuro_yurist_news.py', encoding='utf-8') as f:
    lines = f.readlines()

# Find line 256 which is ']' - that's the end of POSTS
# Then find the REAL function body - look for '    """Отправляет 12'
posts_end = 255  # 0-indexed line 256

real_func_start = None
for i, line in enumerate(lines):
    if i > posts_end and '"""Отправляет 12 новостей в чат НейроЮрист."""' in line:
        # go back 1 line to get the async def line
        real_func_start = i - 1
        break

if real_func_start is None:
    # fallback: find by content of function
    for i, line in enumerate(lines):
        if i > posts_end and 'client = TelegramClient(SESSION_FILE' in line:
            real_func_start = i - 2
            break

print(f'POSTS ends at line {posts_end+1}, real func starts at line {real_func_start+1 if real_func_start else "NOT FOUND"}')

if real_func_start is not None:
    clean_lines = lines[:posts_end+1] + ['\n', '\n'] + lines[real_func_start:]
    with open('send_neuro_yurist_news.py', 'w', encoding='utf-8') as f:
        f.writelines(clean_lines)
    print(f'Done. Total lines: {len(clean_lines)}')
else:
    print('Could not find real function start!')
