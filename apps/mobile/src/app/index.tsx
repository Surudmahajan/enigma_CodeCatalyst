import { Redirect } from 'expo-router';

import { Skeleton } from '@/components/ui';
import { useAuth } from '@/lib/auth-store';

/** Entry gate: auth → organization onboarding → workspace. */
export default function Index() {
  const { status, me } = useAuth();
  if (status === 'loading') return <Skeleton count={1} height={2} />;
  if (status === 'signedOut') return <Redirect href="/login" />;
  if (!me?.memberships.length) return <Redirect href="/onboarding" />;
  return <Redirect href="/(tabs)" />;
}
