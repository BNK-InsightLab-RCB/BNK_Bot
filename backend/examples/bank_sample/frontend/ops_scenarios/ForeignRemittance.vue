<template>
  <section>
    <h1>외화송금</h1>
    <label>송금인 고객번호 <input v-model="form.customerNo" /></label>
    <label>수취인명 <input v-model="form.beneficiaryName" /></label>
    <label>송금금액 <input v-model.number="form.amountUsd" /></label>
    <label>증빙서류번호 <input v-model="form.documentNo" /></label>
    <button type="button" @click="requestForeignRemittance">송금신청</button>
  </section>
</template>

<script setup lang="ts">
import axios from "axios";

const screenId = "FX_510";
const screenName = "외화송금";
const menuId = "MENU_FX_REMITTANCE";

const form = {
  customerNo: "",
  beneficiaryName: "",
  amountUsd: 0,
  documentNo: "",
  countryCode: "",
};

function requestForeignRemittance() {
  if (!form.customerNo || !form.beneficiaryName) {
    alert("송금인과 수취인 정보를 확인하세요.");
    return;
  }
  if (!form.amountUsd || form.amountUsd <= 0) {
    alert("송금금액을 확인하세요.");
    return;
  }
  if (!form.documentNo) {
    alert("증빙서류를 첨부하세요.");
    return;
  }
  return axios.post("/api/ops/fx/remit", form);
}
</script>
