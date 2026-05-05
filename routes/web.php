<?php

use Illuminate\Support\Facades\Route;
use Inertia\Inertia;

// 將首頁直接指向你的 X 風格對話頁面
Route::get('/', function () {
    return Inertia::render('chat');
})->name('home');



require __DIR__.'/settings.php';