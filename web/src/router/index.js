import { createRouter, createWebHashHistory } from 'vue-router'
import Home from '../views/Home.vue'
import Login from '../views/Login.vue'
import Register from '../views/Register.vue'

const routes = [
  { path: '/', name: 'home', component: Home },
  { path: '/login', name: 'login', component: Login },
  { path: '/register', name: 'register', component: Register }
]

const router = createRouter({
  history: createWebHashHistory(),
  routes
})

// 登录守卫：未登录访问受限页面时跳转到登录页
router.beforeEach((to) => {
  const publicPages = ['/login', '/register']
  const authed = !!localStorage.getItem('auth_user')
  if (!authed && !publicPages.includes(to.path)) {
    return '/login'
  }
  if (authed && publicPages.includes(to.path)) {
    return '/'
  }
  return true
})

export default router
