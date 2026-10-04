# دليل التشغيل الآلي — «دقيقة عقار»

هذا الملف تنفّذه المهمة المجدولة `daqiqa-aqar-daily` كل يوم الساعة 07:30 (توقيت الرياض). لا يُطلب من محمود أي عمل يدوي؛ دوره الاعتماد فقط.

## القواعد الثابتة
1. **لا يُنشر شيء لم يمر من بوابة الامتثال** (`engine/compliance.py`). أي حلقة «محجوب» لا تُنتج ولا تُجدول.
2. **لا حذف** لمنشورات Buffer أو ملفات. التعديل يكون بتحويل المنشور إلى مسودة (`edit_post` مع `saveToDraft: true`).
3. نجدول يومًا واحدًا مقدّمًا فقط (منشور واحد على تيك توك).
4. **لا تلمس قناة تيك توك daqiqa_ai** — هي لبرنامج «دقيقة ذكاء». القناة الوحيدة لهذا البرنامج: @daqiqa_aqar.
5. إذا كان `buffer.live` في `config.json` = `false` ⇒ أنتج وجهّز التقرير فقط، ولا تنشئ منشورات.

## المعرّفات
- Buffer: المنظمة `6a815081358dd6921c9dd995` (خطة Essentials) · قناة تيك توك **@daqiqa_aqar** `6ac2525f6a5c39ccb60fd271` — النشر يوميًا 19:30. لا تنشر على لينكدإن أو إكس.
- مجلد الفيديوهات المحلي: `H:\ملفاتي\cloude\تيك توك - دقيقة ذكاء\videos\دقيقة عقار\` — يتزامن مع Drive داخل المجلد المشارك بالرابط `1psVcFWwDtJW-Q7xV7RZNeUjAfV0INZO2`.
- رابط الفيديو لـ Buffer: `https://drive.google.com/uc?export=download&id={drive_id}&confirm=t`

## الإجراء اليومي (بالترتيب)
**1) الإنتاج المسبق**
`python engine/ops.py produce-next` — يحافظ على حلقتين منتجتين جاهزتين على الأقل. كل حلقة تمر: بوابة الامتثال ← الصوت ← الفيديو ← فحص الجودة (المدة ≤ 60 ث، وجود الصوت والصورة 1080×1920).

**2) الجدولة لليوم التالي** (فقط إذا `live = true`)
- `python engine/ops.py plan` ⇒ إذا `action = schedule`:
  - إن كان `drive_id` فارغًا: `search_files` بـ `title = '<video_file>'`، ثم `python engine/ops.py set ID drive_id=<id>`. إن لم يظهر الملف بعد (التزامن) أعد المحاولة بعد 10 دقائق مرة واحدة، ثم سجّل وانتقل.
  - `list_posts` (scheduled) للمنظمة: تأكد أن نفس الملف غير مجدول، وأن العدد الكلي < 9.
  - لكل قناة في `slots`: `create_post` بـ `channelId`، `schedulingType: automatic`، `mode: customScheduled`، `dueAt` من الخطة، `text` = `text`، `assets: [{video: {url: <رابط Drive>, metadata: {title: "<video_file بدون الامتداد>"}}}]`، `metadata: {tiktok: {isAiGenerated: true}}`.
  - بعد كل منشور: `python engine/ops.py posted ID tiktok <post_id> <dueAt>`.
- إذا `action = blocked` ⇒ الحلقة حُجبت آليًا؛ خذ التالية بتشغيل `plan` مرة أخرى.

**3) المزامنة والأرقام**
- `list_posts` (sent) لآخر 7 أيام لقناة @daqiqa_aqar؛ لكل منشور يطابق `post_id` مسجّلًا سجّل الأرقام: `python engine/ops.py metrics ID CHANNEL views=.. likes=.. comments=.. shares=..`.
- منشور حالته error ⇒ `ops.py set ID status=منتج posts=null` ليعاد جدولته، وسجّل `publish_failed`.

**4) التقرير**
`python engine/ops.py report` ⇒ يحدّث `dashboard.html` و`reports/YYYY-MM-DD.md`.

## التنبيهات (PushNotification لمحمود — سطر واحد فقط)
- فشل الإنتاج أو النشر مرتين متتاليتين.
- المخزون المتبقي (`days_of_content_left`) أقل من 7 أيام.
- يوم الأحد: ملخص أسبوعي من سطرين (المنشور، المشاهدات، أي حجب).
لا تنبّه في الأيام العادية الناجحة.

## الصيانة الدورية (آلية)
- كل أحد: أي معلومة `review_by` لها خلال 14 يومًا ⇒ أعد التحقق من مصدرها الرسمي (WebSearch/WebFetch على النطاق الحكومي). إن ثبتت: حدّث `review_by` و`accessed` في `content/facts.json`. إن تغيّر النظام: عدّل النص وفق المصدر الجديد، أو اجعل `confidence: medium` لتُحجب.
- عندما يقل المخزون عن 10: أضف 10 معلومات جديدة بنفس المخطط والشروط (مصدر رسمي فُتح فعلًا، فصحى رسمية، ≤ 80 كلمة للمتن)، ثم `python engine/compliance.py` للتأكد.
- إذا وُجد `GEMINI_API_KEY` ومكتبة المقدم أقل من 6 مقاطع: `python engine/gemini_presenter.py`.

## مكتبة لقطات المذيع (Veo من اشتراك Gemini Pro — بدون تكلفة إضافية)
- اللقطات في `assets/presenter/clip_XX.mp4` (مولّدة من صورة محمود الحقيقية عبر gemini.google.com/u/2 بوصف «أسلوب كرتوني ثلاثي الأبعاد ناعم وواقعي الإضاءة» — الوصف الواقعي الصريح يُرفض).
- كل حلقة تختار لقطة عشوائية. إذا المكتبة أقل من 6 لقطات وكان Claude in Chrome متصلًا: ولّد لقطة جديدة واحدة (زاوية/مشهد مختلف) ونزّلها وأضفها. لا تستخدم الصورة الثابتة إذا وُجدت لقطات.
