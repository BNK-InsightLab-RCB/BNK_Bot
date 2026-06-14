<template>
  <section>
    <h1>전표승인</h1>
    <button type="button" @click="approveSlip">승인</button>
  </section>
</template>

<script setup lang="ts">
import axios from "axios";

const screenId = "SLIP_010";
const screenName = "전표승인";
const menuId = "MENU_SLIP_APPROVAL";

const form = {
  slipNo: "",
};

function approveSlip() {
  if (!form.slipNo) {
    alert("전표번호를 입력하세요.");
    return;
  }

  return axios.post("/api/slip/approve", form);
}
</script>
