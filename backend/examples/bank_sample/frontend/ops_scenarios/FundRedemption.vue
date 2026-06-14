<template>
  <section>
    <h1>펀드 환매</h1>
    <label>펀드계좌번호 <input v-model="form.fundAccountNo" /></label>
    <label>환매좌수 <input v-model.number="form.units" /></label>
    <button type="button" @click="redeemFund">환매신청</button>
  </section>
</template>

<script setup lang="ts">
import axios from "axios";

const screenId = "FUND_410";
const screenName = "펀드 환매";
const menuId = "MENU_FUND_REDEMPTION";

const form = {
  fundAccountNo: "",
  units: 0,
  riskProfileChecked: false,
};

function redeemFund() {
  if (!form.fundAccountNo) {
    alert("펀드계좌번호를 입력하세요.");
    return;
  }
  if (!form.units || form.units <= 0) {
    alert("환매좌수를 확인하세요.");
    return;
  }
  return axios.post("/api/ops/fund/redeem", form);
}
</script>
