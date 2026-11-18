import { DOCUMENT } from '@angular/common';
import { Injectable, inject, signal } from '@angular/core';

export type Lang = 'en' | 'ar';

const DICT: Record<string, { en: string; ar: string }> = {
  dashboard: { en: 'Dashboard', ar: 'لوحة المعلومات' },
  map: { en: 'City map', ar: 'خريطة المدينة' },
  devices: { en: 'Devices', ar: 'الأجهزة' },
  alarms: { en: 'Alarms', ar: 'الإنذارات' },
  commands: { en: 'Commands', ar: 'الأوامر' },
  automation: { en: 'Automation', ar: 'الأتمتة' },
  integrations: { en: 'Integrations', ar: 'التكاملات' },
  assistant: { en: 'AI assistant', ar: 'المساعد الذكي' },
  open_alarms: { en: 'Open alarms', ar: 'الإنذارات المفتوحة' },
  critical: { en: 'Critical (P1)', ar: 'حرجة (P1)' },
  devices_total: { en: 'Devices', ar: 'الأجهزة' },
  offline: { en: 'Offline', ar: 'غير متصل' },
  pending_approvals: { en: 'Pending approvals', ar: 'موافقات معلقة' },
  ack: { en: 'Acknowledge', ar: 'إقرار' },
  shelve: { en: 'Shelve', ar: 'تأجيل' },
  clear: { en: 'Clear', ar: 'مسح' },
  approve: { en: 'Approve', ar: 'موافقة' },
  reject: { en: 'Reject', ar: 'رفض' },
  suggest: { en: 'AI triage', ar: 'فرز ذكي' },
  send: { en: 'Send', ar: 'إرسال' },
  ask_placeholder: { en: 'Ask about the city, an alarm or a device…', ar: 'اسأل عن المدينة أو إنذار أو جهاز…' },
  search: { en: 'Search', ar: 'بحث' },
  type: { en: 'Type', ar: 'النوع' },
  status: { en: 'Status', ar: 'الحالة' },
  priority: { en: 'Priority', ar: 'الأولوية' },
  entity: { en: 'Entity', ar: 'الكيان' },
  raised: { en: 'Raised', ar: 'وقت الإنذار' },
  message: { en: 'Message', ar: 'الرسالة' },
  history: { en: 'History', ar: 'السجل' },
  send_command: { en: 'Send command', ar: 'إرسال أمر' },
  action: { en: 'Action', ar: 'الإجراء' },
  params: { en: 'Parameters (JSON)', ar: 'المعاملات (JSON)' },
  draft_workflow: { en: 'Draft workflow with AI', ar: 'إنشاء سير عمل بالذكاء الاصطناعي' },
  describe_automation: { en: 'Describe the automation you need', ar: 'صف الأتمتة المطلوبة' },
  generate: { en: 'Generate draft', ar: 'إنشاء مسودة' },
  open_node_red: { en: 'Open Node-RED', ar: 'فتح Node-RED' },
  download: { en: 'Download JSON', ar: 'تنزيل JSON' },
  webhooks: { en: 'Outbound webhooks', ar: 'الويب هوك الصادرة' },
  add: { en: 'Add', ar: 'إضافة' },
  delete: { en: 'Delete', ar: 'حذف' },
  logout: { en: 'Sign out', ar: 'تسجيل الخروج' },
  no_data: { en: 'No data', ar: 'لا توجد بيانات' },
  approval_note: {
    en: 'Proposed actions run only after you approve them.',
    ar: 'لا يتم تنفيذ الإجراءات المقترحة إلا بعد موافقتك.',
  },
};

@Injectable({ providedIn: 'root' })
export class I18nService {
  private readonly doc = inject(DOCUMENT);
  readonly lang = signal<Lang>((localStorage.getItem('omnilink.lang') as Lang) || 'en');

  constructor() {
    this.apply(this.lang());
  }

  t(key: string): string {
    const e = DICT[key];
    return e ? e[this.lang()] : key;
  }

  toggle(): void {
    this.set(this.lang() === 'en' ? 'ar' : 'en');
  }

  set(lang: Lang): void {
    this.lang.set(lang);
    try {
      localStorage.setItem('omnilink.lang', lang);
    } catch {
      /* storage may be unavailable */
    }
    this.apply(lang);
  }

  private apply(lang: Lang): void {
    this.doc.documentElement.lang = lang;
    this.doc.documentElement.dir = lang === 'ar' ? 'rtl' : 'ltr';
  }
}
