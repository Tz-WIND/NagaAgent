import { definePreset } from '@primeuix/themes'
import Lara from '@primeuix/themes/lara'
import PrimeVue from 'primevue/config'
import ToastService from 'primevue/toastservice'
import { createApp } from 'vue'

import { createRouter, createWebHashHistory } from 'vue-router'
import App from './App.vue'
import './style.css'
import 'virtual:uno.css'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', component: () => import('@/views/PanelView.vue') },
    { path: '/chat', component: () => import('@/views/MessageView.vue') },
    { path: '/model', component: () => import('@/views/TravelView.vue') },
    {
      path: '/forum',
      component: () => import('@/forum/ForumLayout.vue'),
      children: [
        { path: '', component: () => import('@/forum/ForumListView.vue') },
        { path: 'my-posts', component: () => import('@/forum/ForumMyPostsView.vue') },
        { path: 'my-replies', component: () => import('@/forum/ForumMyRepliesView.vue') },
        { path: 'messages', component: () => import('@/forum/ForumMessagesView.vue') },
        { path: 'friends', component: () => import('@/forum/ForumFriendsView.vue') },
        { path: 'quota', component: () => import('@/forum/ForumQuotaView.vue') },
        { path: ':id', component: () => import('@/forum/ForumPostView.vue') },
      ],
    },
    { path: '/memory', component: () => import('@/views/MemoryView.vue') },
    { path: '/mind', component: () => import('@/views/MindView.vue') },
    { path: '/skill', component: () => import('@/views/SkillView.vue') },
    { path: '/config', component: () => import('@/views/ConfigView.vue') },
    { path: '/music', component: () => import('@/views/MusicView.vue') },
    { path: '/music/edit', component: () => import('@/views/MusicEditView.vue') },
    { path: '/market', component: () => import('@/views/MarketView.vue') },
    { path: '/float', component: () => import('@/views/FloatingView.vue') },
  ],
})

createApp(App)
  .use(PrimeVue, {
    theme: {
      preset: definePreset(Lara),
      options: {
        darkModeSelector: '.p-dark',
      },
    },
  })
  .use(ToastService)
  .use(router)
  .mount('#app')
