<script setup lang="ts">
import BoxContainer from '@/components/BoxContainer.vue'
import { useTravel } from '@/travel/composables/useTravel'
import TravelConfigForm from '@/travel/components/TravelConfigForm.vue'
import TravelRunningPanel from '@/travel/components/TravelRunningPanel.vue'
import TravelResultPanel from '@/travel/components/TravelResultPanel.vue'
import TravelHistoryList from '@/travel/components/TravelHistoryList.vue'

const {
  travelSession, isRunning, isCompleted, historyList, loading,
  timeProgress, creditProgress, startTravel, stopTravel, viewSession,
} = useTravel()
</script>

<template>
  <BoxContainer class="text-sm">
    <div class="flex flex-col gap-5 p-2 pb-8">
      <TravelRunningPanel
        v-if="isRunning && travelSession"
        :session="travelSession"
        :time-progress="timeProgress"
        :credit-progress="creditProgress"
        @stop="stopTravel"
      />

      <TravelResultPanel
        v-else-if="isCompleted && travelSession"
        :session="travelSession"
        @new-travel="travelSession = null"
      />

      <template v-else>
        <TravelConfigForm :loading="loading" @start="startTravel" />
        <div class="border-t border-white/8 my-1" />
        <TravelHistoryList :sessions="historyList" @select="viewSession" />
      </template>
    </div>
  </BoxContainer>
</template>
