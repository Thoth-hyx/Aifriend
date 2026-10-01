const CONFIG_API = {
    HTTP_URL: import.meta.env.VITE_API_URL || '',
    VAD_URL: import.meta.env.VITE_VAD_URL || `${import.meta.env.BASE_URL}vad/`,
}

export default CONFIG_API
