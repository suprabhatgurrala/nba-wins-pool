<script setup lang="ts">
import { onMounted } from 'vue'
import { useAuctionData } from '@/composables/useAuctionData';
import AuctionTable from '@/components/pool/AuctionTable.vue';

const {
  auctionTableData,
  error: error,
  loading: loading,
  fetchAuctionData,
} = useAuctionData("")

onMounted(() => {
  fetchAuctionData()
})
</script>

<template>
  <main>
    <div class="home">
      <span>
        <h1 class="title">🏀 NBA Wins Pool 🏆</h1>
      </span>

      <h1>Auction</h1>

      <AuctionTable v-if="!loading" :auctionTableData="auctionTableData" />
      <p v-else-if="error">{{ error }}</p>
      <p v-else>Loading auction data...</p>
    </div>
  </main>
</template>
