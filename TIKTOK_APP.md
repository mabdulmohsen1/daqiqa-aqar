# تطبيق تيك توك للنشر المباشر — «دقيقة عقار»

الهدف: أن ينشر تطبيق AI Studio الفيديو مباشرة على @daqiqa_aqar بدون Buffer.

## خطوات محمود (مرة واحدة، 10 دقائق تقريبًا)
1. ادخل https://developers.tiktok.com وسجّل الدخول بحساب @daqiqa_aqar، ثم Manage apps ← Connect an app.
2. انسخ البيانات التالية في النموذج كما هي.
3. بعد الحفظ أرسل لي «تم» وأكمل أنا: التحقق من النطاق، الربط، وتقديم المراجعة.

## بيانات النموذج
| الحقل | القيمة |
|---|---|
| App name | Daqiqat Aqar |
| Category | Education |
| Description | Publishes one verified, ≤60-second educational video per day about Saudi real-estate regulations to the creator's own TikTok account. Content is produced automatically from official government sources and posted only to the account owner's profile. |
| Terms of Service URL | https://mbr.sa/terms.html |
| Privacy Policy URL | https://mbr.sa/privacy.html |
| Platforms | Web |
| Website URL | https://mbr.sa |
| Products | Login Kit + Content Posting API (Direct Post مفعّل) |
| Scopes | user.info.basic, video.upload, video.publish |
| Redirect URI | (أضيفه بعد نشر تطبيق AI Studio — رابطه + `/auth/tiktok/callback`) |

## مرحلة المراجعة (Audit)
- قبل موافقة تيك توك: أي نشر عبر الـ API يظهر **خاصًا (SELF_ONLY)** فقط.
- المراجعة تطلب فيديو قصير يوضح تدفق التطبيق — أجهّزه أنا من تطبيق AI Studio.
- المدة المعتادة: أيام إلى أسابيع، وقد تُرفض ويُعاد التقديم.
- إلى أن تتم الموافقة يبقى النشر عن طريق Buffer.
