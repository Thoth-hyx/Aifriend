import {defineStore} from "pinia";
import {ref} from "vue";
import valentine from "daisyui/theme/valentine/index.js";

export const useUserStore = defineStore('user',()=>{
    const id = ref(0)
    const username = ref('')
    const photo = ref('')
    const profile = ref('')
    const canCloneVoice = ref(false)
    const accessToken = ref('')
    const hasPulledUserInfo = ref(false)

    function isLogin(){
        return !!accessToken.value
    }

    function setAccessToken(token){
        accessToken.value = token
    }

    function setUserInfo(data){
        id.value = data.user_id
        username.value = data.username
        photo.value = data.photo
        profile.value = data.profile
        canCloneVoice.value = data.can_clone_voice === true
    }

    function logout(){
        id.value = 0
        username.value = ''
        photo.value = ''
        profile.value = ''
        canCloneVoice.value = false
        accessToken.value = ''
    }

    function setHasPulledUserInfo(newStatus){
        hasPulledUserInfo.value = newStatus
    }

    return{
        id,
        username,
        photo,
        profile,
        canCloneVoice,
        accessToken,
        setAccessToken,
        isLogin,
        setUserInfo,
        logout,
        hasPulledUserInfo,
        setHasPulledUserInfo,
    }
})

