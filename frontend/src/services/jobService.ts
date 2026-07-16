import api from './api';
import type { BulkJob } from '../types/jobs';

export const jobService = {
  async get(id: number): Promise<BulkJob> {
    const { data } = await api.get<BulkJob>(`/api/v1/jobs/${id}/`);
    return data;
  },
};
