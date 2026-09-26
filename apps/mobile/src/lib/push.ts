import Constants from 'expo-constants';
import * as Device from 'expo-device';
import * as Notifications from 'expo-notifications';
import { router } from 'expo-router';
import { Platform } from 'react-native';

import { api } from './api';

Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowBanner: true, shouldShowList: true, shouldPlaySound: false, shouldSetBadge: true,
  }),
});

/**
 * Ask for permission and register this device's Expo push token with the backend.
 * Requires a physical device and an EAS project id (app.json → extra.eas.projectId);
 * without them the app still works with in-app notification history.
 */
export async function registerForPush(): Promise<void> {
  if (Platform.OS === 'web' || !Device.isDevice) return;
  const projectId = Constants.expoConfig?.extra?.eas?.projectId as string | undefined;
  if (!projectId) return;
  if (Platform.OS === 'android') {
    await Notifications.setNotificationChannelAsync('default', {
      name: 'SYMBIO', importance: Notifications.AndroidImportance.DEFAULT,
    });
  }
  let { status } = await Notifications.getPermissionsAsync();
  if (status !== 'granted') ({ status } = await Notifications.requestPermissionsAsync());
  if (status !== 'granted') return;
  const token = (await Notifications.getExpoPushTokenAsync({ projectId })).data;
  await api.post('/notifications/push-tokens', { token, platform: Platform.OS });
}

/** Open the relevant screen when a notification is tapped (data carries ids only). */
export function listenForNotificationTaps() {
  const subscription = Notifications.addNotificationResponseReceivedListener((response) => {
    const data = response.notification.request.content.data as Record<string, string | undefined>;
    if (data.conversation_id) router.push(`/conversation/${data.conversation_id}`);
    else if (data.exchange_id) router.push(`/exchange/${data.exchange_id}`);
    else if (data.match_id) router.push(`/match/${data.match_id}`);
  });
  return () => subscription.remove();
}
