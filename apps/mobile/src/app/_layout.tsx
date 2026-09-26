import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { DarkTheme, DefaultTheme, Stack, ThemeProvider } from 'expo-router';
import * as SplashScreen from 'expo-splash-screen';
import { StatusBar } from 'expo-status-bar';
import { useEffect, useState } from 'react';
import { useColorScheme } from 'react-native';

import { ApiError } from '@/lib/api';
import { useAuth } from '@/lib/auth-store';
import { setupNetworkAwareness } from '@/lib/network';
import { listenForNotificationTaps, registerForPush } from '@/lib/push';
import { useColors } from '@/theme';

SplashScreen.preventAutoHideAsync();

function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        // Don't hammer the API on permission/validation errors; retry transient ones.
        retry: (count, error) => !(error instanceof ApiError && error.status >= 400 && error.status < 500) && count < 2,
      },
    },
  });
}

export default function RootLayout() {
  const scheme = useColorScheme();
  const colors = useColors();
  const [queryClient] = useState(createQueryClient);
  const status = useAuth((s) => s.status);
  const organizationId = useAuth((s) => s.organizationId);

  useEffect(() => {
    useAuth.getState().bootstrap().finally(() => SplashScreen.hideAsync());
    const stopNetwork = setupNetworkAwareness();
    const stopTaps = listenForNotificationTaps();
    return () => { stopNetwork(); stopTaps(); };
  }, []);

  useEffect(() => {
    if (status === 'signedIn') registerForPush().catch(() => undefined);
    if (status === 'signedOut') queryClient.clear();
  }, [status, queryClient]);

  useEffect(() => { queryClient.invalidateQueries(); }, [organizationId, queryClient]);

  const base = scheme === 'dark' ? DarkTheme : DefaultTheme;
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider value={{ ...base, colors: { ...base.colors, background: colors.background, card: colors.surface,
        text: colors.text, border: colors.border, primary: colors.accent } }}>
        <StatusBar style="auto" />
        <Stack screenOptions={{ headerBackTitle: 'Back', headerTitleStyle: { fontWeight: '700' } }}>
          <Stack.Screen name="index" options={{ headerShown: false }} />
          <Stack.Screen name="(auth)" options={{ headerShown: false }} />
          <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
          <Stack.Screen name="onboarding" options={{ title: 'Your organization' }} />
          <Stack.Screen name="resource/new" options={{ title: 'New resource', presentation: 'modal' }} />
          <Stack.Screen name="requirement/new" options={{ title: 'New requirement', presentation: 'modal' }} />
          <Stack.Screen name="resource/[id]" options={{ title: 'Resource' }} />
          <Stack.Screen name="requirement/[id]" options={{ title: 'Requirement' }} />
          <Stack.Screen name="match/[id]" options={{ title: 'Opportunity' }} />
          <Stack.Screen name="conversation/[id]" options={{ title: 'Private channel' }} />
          <Stack.Screen name="exchange/new" options={{ title: 'Record exchange', presentation: 'modal' }} />
          <Stack.Screen name="exchange/[id]" options={{ title: 'Exchange' }} />
          <Stack.Screen name="pathways/[id]" options={{ title: 'Processing pathways' }} />
          <Stack.Screen name="impact" options={{ title: 'Impact' }} />
          <Stack.Screen name="notifications" options={{ title: 'Notifications' }} />
        </Stack>
      </ThemeProvider>
    </QueryClientProvider>
  );
}
