"use server";

import { createClient } from "@/utils/supabase/server";
import { headers } from "next/headers";
import { redirect } from "next/navigation";

export async function loginWithEmail(email: string, password: string) {
  const supabase = await createClient();
  const { data, error } = await supabase.auth.signInWithPassword({
    email,
    password,
  });

  if (error) return { error: error.message };
  return { data };
}

async function getOrigin(): Promise<string | null> {
  const headersList = await headers();
  return headersList.get("origin");
}

export async function signUpWithEmail(email: string, password: string) {
  const supabase = await createClient();
  const origin = await getOrigin();

  const { data, error } = await supabase.auth.signUp({
    email,
    password,
    options: {
      emailRedirectTo: `${origin}/auth/callback`,
    },
  });

  if (error) return { error: error.message };
  return { data };
}

export async function logOut() {
  const supabase = await createClient();
  await supabase.auth.signOut();
  redirect("/");
}

// Only providers actually configured in supabase/config.toml. Adding one here
// without wiring its credentials produces a button that fails on click, so the
// type is deliberately narrow — widen it and the config together.
export async function getOAuthUrl(
  provider: "google" | "github",
  nextPath: string = "/",
) {
  const supabase = await createClient();
  const origin = await getOrigin();

  const { data, error } = await supabase.auth.signInWithOAuth({
    provider,
    options: {
      redirectTo: `${origin}/auth/callback?next=${encodeURIComponent(nextPath)}`,
    },
  });

  if (error) return { error: error.message };
  return { url: data.url };
}

export async function resetPassword(email: string) {
  const supabase = await createClient();
  const origin = await getOrigin();

  const { error } = await supabase.auth.resetPasswordForEmail(email, {
    redirectTo: `${origin}/auth/callback?next=/auth/update-password`,
  });
  
  if (error) return { error: error.message };
  return { success: true };
}

export async function updatePassword(password: string) {
  const supabase = await createClient();
  const { error } = await supabase.auth.updateUser({
    password: password
  });

  if (error) return { error: error.message };
  return { success: true };
}

export async function deleteUserAccount() {
  const supabase = await createClient();
  const { error } = await supabase.rpc('delete_user');
  
  if (error) return { error: error.message };

  await supabase.auth.signOut();
  redirect("/");
}

export async function getUserProfile() {
  const supabase = await createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) return null;
  
  const { data, error } = await supabase.from('profiles').select('*').eq('id', user.id).single();
  if (error) return null;
  return data;
}

export async function updateProfileData(fullName: string, avatarUrl?: string | null) {
  const supabase = await createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) return { error: "Not authenticated" };

  const updatePayload: { full_name: string; avatar_url?: string | null } = {
    full_name: fullName
  };

  if (avatarUrl !== undefined) {
    updatePayload.avatar_url = avatarUrl;
  }

  const { error } = await supabase.from('profiles').update(updatePayload).eq('id', user.id);

  if (error) return { error: error.message };
  return { success: true };
}

export async function uploadAvatar(formData: FormData) {
  const supabase = await createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) return { error: "Not authenticated" };

  const file = formData.get("avatar") as File;
  if (!file) return { error: "No file provided" };

  const allowedExtensions = ["jpg", "jpeg", "png", "gif", "webp"];
  const fileExt = file.name.split('.').pop()?.toLowerCase();
  if (!fileExt || !allowedExtensions.includes(fileExt)) {
    return { error: "Invalid file type. Allowed: jpg, jpeg, png, gif, webp" };
  }
  const fileName = `${user.id}-${Date.now()}.${fileExt}`;
  const filePath = `${user.id}/${fileName}`;

  const { error: uploadError } = await supabase.storage
    .from('avatars')
    .upload(filePath, file, { upsert: true });

  if (uploadError) return { error: uploadError.message };

  const { data: { publicUrl } } = supabase.storage
    .from('avatars')
    .getPublicUrl(filePath);

  const { error: updateError } = await supabase.from('profiles')
    .update({ avatar_url: publicUrl })
    .eq('id', user.id);

  if (updateError) return { error: updateError.message };

  return { success: true, avatarUrl: publicUrl };
}
export async function updateSettings(settings: {
  enter_to_send?: boolean;
  memory_paused?: boolean;
  preferred_language?: string;
  preferred_model?: string;
  theme?: string;
}) {
  const supabase = await createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) return { error: "Not authenticated" };

  const { error } = await supabase
    .from('profiles')
    .update(settings)
    .eq('id', user.id);

  if (error) return { error: error.message };
  return { success: true };
}