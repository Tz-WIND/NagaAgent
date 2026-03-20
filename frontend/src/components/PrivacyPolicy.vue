<script setup lang="ts">
import Button from 'primevue/button'
import Dialog from 'primevue/dialog'

defineProps<{ visible: boolean }>()
defineEmits<{ 'update:visible': [value: boolean] }>()
</script>

<template>
  <Dialog
    :visible="visible"
    modal
    header="隐私政策"
    :style="{ width: '640px' }"
    @update:visible="$emit('update:visible', $event)"
  >
    <div class="agreement-content">
      <h3>娜迦智能体隐私政策</h3>
      <p class="update-date">更新日期：2026 年 3 月</p>

      <section>
        <h4>一、我们收集的信息</h4>
        <p>为提供账号登录、论坛互动、探索通知和问题排查等能力，我们会收集必要的账号信息与服务日志，包括用户名、邮箱、登录状态、客户端版本、基础错误日志等。</p>
        <p>您在本地客户端中的对话、探索结果、干员数据、上传文档和大部分业务数据，默认优先保存在您本地设备或您主动配置的服务中。</p>
      </section>

      <section>
        <h4>二、信息的使用方式</h4>
        <p>我们仅在以下范围内使用相关信息：</p>
        <ul>
          <li>完成注册、登录、刷新身份状态等账号能力；</li>
          <li>支持论坛发帖、评论、点赞、探索结果回传等网络功能；</li>
          <li>用于安全风控、故障诊断、产品优化与服务稳定性维护；</li>
          <li>在获得您明确配置或授权后，将通知、探索报告发送到飞书、QQ 等外部通道。</li>
        </ul>
      </section>

      <section>
        <h4>三、本地数据与第三方服务</h4>
        <p>本产品支持接入第三方大模型、浏览器自动化、MCP 服务及论坛后端。您主动启用这些能力时，相关请求数据会按对应服务的协议被处理。</p>
        <p>我们建议您不要在对话、探索任务或上传文件中输入不必要的高敏感信息。涉及第三方服务时，请同时遵守对应服务方的隐私条款与数据政策。</p>
      </section>

      <section>
        <h4>四、信息共享与披露</h4>
        <p>除以下情形外，我们不会向无关第三方出售您的个人信息：</p>
        <ul>
          <li>获得您的明确授权；</li>
          <li>为实现您主动启用的功能所必需；</li>
          <li>依据法律法规、司法程序或监管要求需要披露。</li>
        </ul>
      </section>

      <section>
        <h4>五、数据安全</h4>
        <p>我们会尽力通过访问控制、鉴权校验、最小必要原则和错误日志脱敏等方式保护您的数据安全。但请理解，任何网络传输和存储系统都不可能绝对安全。</p>
      </section>

      <section>
        <h4>六、您的权利</h4>
        <p>您可以修改账号信息、清理本地数据、停止外部通知、退出登录，或删除本地生成的会话与干员数据。若您需要处理平台侧账号信息，可通过产品内提供的联系方式与我们沟通。</p>
      </section>

      <section>
        <h4>七、联系我们</h4>
        <p>如您对本隐私政策有疑问，可通过以下方式联系我们：</p>
        <ul>
          <li>B 站：<b>柏斯阔落</b></li>
          <li>QQ 频道：<b>nagaagent1</b></li>
        </ul>
      </section>
    </div>

    <template #footer>
      <Button label="关闭" icon="pi pi-times" @click="$emit('update:visible', false)" />
    </template>
  </Dialog>
</template>

<style scoped>
.agreement-content {
  max-height: 420px;
  overflow-y: auto;
  padding-right: 8px;
  font-size: 13px;
  line-height: 1.7;
  color: var(--p-surface-200, #ccc);
}

.agreement-content h3 {
  margin: 0 0 4px;
  font-size: 16px;
  font-weight: 600;
  text-align: center;
  color: rgba(212, 175, 55, 0.9);
}

.update-date {
  text-align: center;
  font-size: 12px;
  color: var(--p-surface-400, #888);
  margin-bottom: 12px;
}

.agreement-content h4 {
  margin: 14px 0 6px;
  font-size: 14px;
  font-weight: 600;
  color: rgba(212, 175, 55, 0.8);
}

.agreement-content p {
  margin: 4px 0;
}

.agreement-content ul {
  margin: 4px 0 4px 20px;
  padding: 0;
  list-style: disc;
}

.agreement-content li {
  margin: 2px 0;
}
</style>
