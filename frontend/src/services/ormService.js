import axios from 'axios';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api';

const ormService = {
  getTemplates: async () => {
    const response = await axios.get(`${API_URL}/orm/templates`);
    return response.data;
  },
  createTemplate: async (templateData) => {
    const response = await axios.post(`${API_URL}/orm/templates`, templateData);
    return response.data;
  },
  deleteTemplate: async (templateId) => {
    const response = await axios.delete(`${API_URL}/orm/templates/${templateId}`);
    return response.data;
  },
  updateTemplate: async (templateId, updates) => {
    const response = await axios.patch(`${API_URL}/orm/templates/${templateId}`, updates);
    return response.data;
  },
  getDashboard: async (learnerId) => {
    const url = learnerId ? `${API_URL}/orm/dashboard?learner_id=${learnerId}` : `${API_URL}/orm/dashboard`;
    const response = await axios.get(url);
    return response.data;
  },
  submitAchievement: async (achievementData) => {
    const response = await axios.post(`${API_URL}/orm/achievements`, achievementData);
    return response.data;
  },
  createAssignment: async (assignmentData) => {
    const response = await axios.post(`${API_URL}/orm/assignments`, assignmentData);
    return response.data;
  }
};

export default ormService;
