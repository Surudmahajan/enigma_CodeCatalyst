import { Redirect, Stack } from 'expo-router';

import { useAuth } from '@/lib/auth-store';

export default function AuthLayout() {
  const status = useAuth((s) => s.status);
  if (status === 'signedIn') return <Redirect href="/" />;
  return <Stack screenOptions={{ headerShown: false }} />;
}
