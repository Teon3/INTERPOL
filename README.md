# International Casebook — Demo

Навчальний Flask + SQLite проєкт з інтерфейсом у стилі міжнародної бази повідомлень. Це **не офіційний сайт INTERPOL**, не пов’язаний з INTERPOL і не має доступу до реальних розшукових баз. Використовуйте лише вигадані анкети та фото, на які маєте право.

## Запуск у Windows
1. Встановіть Python 3.11 або новіший.
2. Відкрийте термінал у папці `interpol_site`.
3. Створіть середовище: `python -m venv .venv`
4. Активуйте його: ` .\.venv\Scripts\Activate.ps1` (PowerShell).
5. Встановіть залежності: `pip install -r ../requirements.txt`
6. Задайте змінні середовища (PowerShell):
   - `$env:FLASK_SECRET_KEY = python -c "import secrets; print(secrets.token_hex(32))"` — виконайте генерацію окремо та скопіюйте результат у змінну, наприклад `$env:FLASK_SECRET_KEY = 'вставте_згенерований_ключ'`.
   - `$env:INTERPOL_ADMIN_USERNAME = 'admin'`
   - `$env:INTERPOL_ADMIN_PASSWORD = 'створіть_свій_пароль'`
7. Запустіть: `python app.py`
8. Відкрийте `http://127.0.0.1:5000`.

Не публікуйте сайт як справжній державний/поліцейський ресурс і не додавайте реальні персональні дані.
