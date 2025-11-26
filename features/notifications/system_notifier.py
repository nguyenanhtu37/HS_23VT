from kivy.utils import platform

# ===== Windows AppID for Toast =====
if platform == "win":
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("HS_23VT")
    except Exception:
        pass

def _ensure_android_channel(activity, channel_id, channel_name="Reminders", importance_level=3):
    try:
        from jnius import autoclass
        Build_Version = autoclass('android.os.Build$VERSION')
        if Build_Version.SDK_INT < 26:
            return
        NotificationChannel = autoclass('android.app.NotificationChannel')
        NotificationManager = autoclass('android.app.NotificationManager')
        Context = autoclass('android.content.Context')
        nm = activity.getSystemService(Context.NOTIFICATION_SERVICE)
        importance = 4 if importance_level >= 4 else 3
        channel = NotificationChannel(channel_id, channel_name, importance)
        nm.createNotificationChannel(channel)
    except Exception:
        pass

def notify_system(title: str, message: str, nid: int = 1001):
    if platform == "android":
        try:
            from jnius import autoclass
            PythonActivity = autoclass('org.kivy.android.PythonActivity')
            activity = PythonActivity.mActivity
            NotificationCompat = autoclass('androidx.core.app.NotificationCompat')
            NotificationManagerCompat = autoclass('androidx.core.app.NotificationManagerCompat')
            PendingIntent = autoclass('android.app.PendingIntent')
            Intent = autoclass('android.content.Intent')

            CHANNEL_ID = 'hs23vt.reminders'
            _ensure_android_channel(activity, CHANNEL_ID, "HS_23VT Reminders", importance_level=4)

            intent = Intent(activity, PythonActivity)
            intent.setFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP | Intent.FLAG_ACTIVITY_CLEAR_TOP)
            pending = PendingIntent.getActivity(
                activity, 0, intent,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE
            )

            builder = (
                NotificationCompat.Builder(activity, CHANNEL_ID)
                .setSmallIcon(activity.getApplicationInfo().icon)
                .setContentTitle(title)
                .setContentText(message)
                .setStyle(NotificationCompat.BigTextStyle().bigText(message))
                .setPriority(NotificationCompat.PRIORITY_HIGH)
                .setAutoCancel(True)
                .setContentIntent(pending)
            )
            nm = getattr(NotificationManagerCompat, "from")(activity)
            nm.notify(nid, builder.build())
            return True
        except Exception as e:
            print("Android native noti err:", e)

    try:
        from plyer import notification
        notification.notify(title=title, message=message, app_name="HS_23VT", timeout=5)
        return True
    except Exception as e:
        print("Plyer noti err:", e)
        return False