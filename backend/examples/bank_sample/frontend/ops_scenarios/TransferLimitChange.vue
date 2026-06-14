<template>
  <section>
    <h1>이체한도 변경</h1>
    <label>고객번호 <input v-model="form.customerNo" /></label>
    <label>변경 후 1일 한도 <input v-model.number="form.dailyLimit" /></label>
    <label>보안매체 등급 <input v-model="form.securityLevel" /></label>
    <button type="button" @click="changeTransferLimit">한도변경</button>
  </section>
</template>

<script setup lang="ts">
import axios from "axios";

const screenId = "TRNF_130";
const screenName = "이체한도 변경";
const menuId = "MENU_TRANSFER_LIMIT_CHANGE";

const form = {
  customerNo: "",
  dailyLimit: 0,
  securityLevel: "",
  identityVerified: false,
};

function changeTransferLimit() {
  if (!form.customerNo) {
    alert("고객번호를 입력하세요.");
    return;
  }
  if (!form.dailyLimit || form.dailyLimit <= 0) {
    alert("변경할 이체한도를 입력하세요.");
    return;
  }
  if (!form.securityLevel) {
    alert("보안매체 등급을 확인하세요.");
    return;
  }
  return axios.post("/api/ops/limit/change", form);
}
</script>
