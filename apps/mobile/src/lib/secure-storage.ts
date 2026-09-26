import * as SecureStore from 'expo-secure-store';
import { Platform } from 'react-native';

/**
 * Auth secrets live in the OS keystore (Keychain / Android Keystore) via
 * expo-secure-store — never in AsyncStorage. On web (development only) there
 * is no secure store, so tokens are kept in memory and a reload signs out.
 */
const memory = new Map<string, string>();
const isNative = Platform.OS === 'ios' || Platform.OS === 'android';

export const secureStorage = {
  async get(key: string): Promise<string | null> {
    return isNative ? SecureStore.getItemAsync(key) : (memory.get(key) ?? null);
  },
  async set(key: string, value: string): Promise<void> {
    if (isNative) await SecureStore.setItemAsync(key, value);
    else memory.set(key, value);
  },
  async remove(key: string): Promise<void> {
    if (isNative) await SecureStore.deleteItemAsync(key);
    else memory.delete(key);
  },
};
