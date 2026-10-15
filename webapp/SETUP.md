# راه‌اندازی مینی‌اپ

مبدل تاریخ یک صفحهٔ استاتیک است و به توکن یا سرور پایتون دسترسی نمی‌خواهد.
تلگرام برای باز کردن آن در حالت Web App به آدرس عمومی HTTPS نیاز دارد.

## انتشار روی GitHub Pages

1. تغییرات `webapp` و فایل `.github/workflows/deploy-webapp.yml` را در مخزن قرار دهید.
2. در مخزن، `Settings → Pages → Build and deployment → Source` را روی `GitHub Actions` بگذارید.
3. در `Actions`، گردش‌کار `Publish Mini App` را اجرا کنید. پس از موفقیت، آدرس سایت در نتیجهٔ Deploy نمایش داده می‌شود.
4. آدرس را در مرورگر بررسی کنید؛ سپس در فایل `.env` کنار `main.py` بنویسید:

```env
WEBAPP_URL=https://augverus.github.io/BirthdayBotAnonyNet/
```

این آدرس پیش‌فرض مورد انتظار برای مخزن فعلی است؛ اگر GitHub آدرس دیگری نمایش داد، از همان استفاده کنید.
پس از ذخیره، بات را دوباره اجرا کنید و `/start` بفرستید. دکمهٔ «تبدیل تاریخ» مینی‌اپ را باز می‌کند.

گردش‌کار فقط پوشهٔ `webapp` را منتشر می‌کند. برای مینی‌اپ، فایل `.env`، توکن و دیتابیس را بارگذاری نکنید.

برای اضافه کردن دکمهٔ Open App به پروفایل بات، Main Mini App را هم با همین آدرس در BotFather تنظیم کنید؛
دکمهٔ داخل بات بدون این تنظیم نیز از `WEBAPP_URL` استفاده می‌کند.

مستندات رسمی:
- https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages
- https://core.telegram.org/bots/webapps
