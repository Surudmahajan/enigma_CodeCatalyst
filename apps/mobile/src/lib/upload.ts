import type { DocumentOut } from '@symbio/shared-types';
import * as DocumentPicker from 'expo-document-picker';

import { api } from './api';

export type PickedFile = DocumentPicker.DocumentPickerAsset;

const ACCEPTED = ['application/pdf', 'image/png', 'image/jpeg', 'image/webp', 'text/csv', 'text/plain',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'];

export async function pickDocument(): Promise<PickedFile | null> {
  const result = await DocumentPicker.getDocumentAsync({ type: ACCEPTED, copyToCacheDirectory: true, multiple: false });
  return result.canceled ? null : result.assets[0];
}

/** Upload to /documents. The server re-validates type (from content) and size; the client check is UX only. */
export async function uploadDocument(file: PickedFile, target: { resource_id?: string; requirement_id?: string; conversation_id?: string }) {
  const form = new FormData();
  if (file.file) {
    form.append('file', file.file); // web
  } else {
    // React Native's FormData accepts {uri, name, type} descriptors for local files.
    form.append('file', { uri: file.uri, name: file.name, type: file.mimeType ?? 'application/octet-stream' } as unknown as Blob);
  }
  Object.entries(target).forEach(([key, value]) => value && form.append(key, value));
  return api.upload<DocumentOut>('/documents', form);
}
