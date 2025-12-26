document.addEventListener("DOMContentLoaded", () => {
    const videos = document.querySelectorAll("video");
    videos.forEach(video => {
        video.addEventListener("play", () => {
            alert("Enjoy the recipe, and don't forget to try it yourself!");
        });
    });
});