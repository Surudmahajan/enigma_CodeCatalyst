import type { ListingStatus } from '@symbio/shared-types';
import { Alert, View } from 'react-native';

import { errorMessage } from '@/lib/api';
import { useCan } from '@/lib/auth-store';
import { useListingStatus } from '@/lib/queries';
import { spacing } from '@/theme';

import { Button, Notice } from './ui';

const ACTION_LABEL: Partial<Record<ListingStatus, { title: string; variant?: 'secondary' | 'danger' }>> = {
  ACTIVE: { title: 'Publish / activate' },
  PAUSED: { title: 'Pause', variant: 'secondary' },
  FULFILLED: { title: 'Mark fulfilled', variant: 'secondary' },
  EXPIRED: { title: 'Mark expired', variant: 'secondary' },
  ARCHIVED: { title: 'Archive', variant: 'danger' },
};

/** Buttons for the explicit lifecycle transitions the backend allows from the current status. */
export function ListingActions({ kind, id, status, allowed }: {
  kind: 'resources' | 'requirements'; id: string; status: ListingStatus; allowed: ListingStatus[];
}) {
  const canEdit = useCan('MANAGE_LISTINGS');
  const mutation = useListingStatus(kind);
  if (!canEdit) return null;
  const run = (target: ListingStatus) => {
    const go = () => mutation.mutate({ id, status: target }, { onError: (e) => Alert.alert('Could not update', errorMessage(e)) });
    if (target === 'ARCHIVED') {
      Alert.alert('Archive this listing?', 'It leaves matching permanently but stays in your history.', [
        { text: 'Cancel', style: 'cancel' }, { text: 'Archive', style: 'destructive', onPress: go },
      ]);
    } else go();
  };
  return (
    <View style={{ gap: spacing.sm }}>
      {status === 'EXPIRED' ? <Notice tone="warning">This listing has expired. Update its dates, then reactivate it.</Notice> : null}
      {status === 'DRAFT' ? <Notice>Drafts are private and not matched until published.</Notice> : null}
      {allowed.filter((s) => ACTION_LABEL[s]).map((s) => (
        <Button key={s} title={ACTION_LABEL[s]!.title} variant={ACTION_LABEL[s]!.variant} onPress={() => run(s)}
          loading={mutation.isPending && mutation.variables?.status === s} />
      ))}
    </View>
  );
}
