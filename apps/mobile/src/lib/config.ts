import { Platform } from 'react-native';

/**
 * Backend base URL. Set EXPO_PUBLIC_API_URL for devices/production.
 * The Android emulator reaches the host machine at 10.0.2.2.
 */
const fallback = Platform.OS === 'android' ? 'http://10.0.2.2:8000' : 'http://localhost:8000';

export const API_URL = (process.env.EXPO_PUBLIC_API_URL || fallback).replace(/\/$/, '');
export const API_PREFIX = '/api/v1';
export const WS_URL = API_URL.replace(/^http/, 'ws');
